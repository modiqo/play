"""Harness-neutral structured elicitation contracts."""

from __future__ import annotations

import argparse
import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .harnesses import native_prompt_surfaces
from .render import json_text


class ElicitationError(ValueError):
    pass


NATIVE_SURFACES = native_prompt_surfaces()


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    description: str
    event: str
    recommended: bool = False
    value_field: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class ChoiceSource:
    context: str
    id_field: str
    label_field: str
    description_field: str
    value_source_field: str
    value_field: str
    event: str
    recommended_field: str | None = None


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    selection: str
    choices: tuple[Choice, ...]
    minimum_selected: int = 1
    input_id: str | None = None
    input_label: str | None = None
    input_event: str | None = None
    template_fields: tuple[str, ...] = ()
    choice_source: ChoiceSource | None = None


def parse_question(prompt_id: str, prompt: dict[str, Any]) -> Question:
    text = prompt.get("question")
    selection = prompt.get("selection")
    if not isinstance(text, str) or not text.strip().endswith("?"):
        raise ElicitationError(f"{prompt_id}: question must end in ?")
    if selection not in {"single", "multiple", "text"}:
        raise ElicitationError(f"{prompt_id}: selection must be single, multiple, or text")
    choices: list[Choice] = []
    for raw in prompt.get("choices", []):
        if not isinstance(raw, dict):
            raise ElicitationError(f"{prompt_id}: invalid choice")
        required = ("id", "label", "description", "event")
        if any(not isinstance(raw.get(field), str) or not raw[field] for field in required):
            raise ElicitationError(f"{prompt_id}: every choice needs id, label, description, event")
        choices.append(
            Choice(
                id=raw["id"],
                label=raw["label"],
                description=raw["description"],
                event=raw["event"],
                recommended=bool(raw.get("recommended", False)),
            )
        )
    input_spec = prompt.get("input")
    raw_source = prompt.get("choices_from")
    choice_source = None
    if raw_source is not None:
        if not isinstance(raw_source, dict):
            raise ElicitationError(f"{prompt_id}: choices_from must be an object")
        required_source = (
            "context",
            "id_field",
            "label_field",
            "description_field",
            "value_source_field",
            "value_field",
            "event",
        )
        if any(
            not isinstance(raw_source.get(field), str) or not raw_source[field]
            for field in required_source
        ):
            raise ElicitationError(
                f"{prompt_id}: choices_from needs context, id_field, label_field, "
                "description_field, value_source_field, value_field, and event"
            )
        recommended_field = raw_source.get("recommended_field")
        if recommended_field is not None and (
            not isinstance(recommended_field, str) or not recommended_field
        ):
            raise ElicitationError(
                f"{prompt_id}: choices_from recommended_field must be a non-empty string"
            )
        choice_source = ChoiceSource(
            context=raw_source["context"],
            id_field=raw_source["id_field"],
            label_field=raw_source["label_field"],
            description_field=raw_source["description_field"],
            value_source_field=raw_source["value_source_field"],
            value_field=raw_source["value_field"],
            event=raw_source["event"],
            recommended_field=recommended_field,
        )
    if selection == "text":
        if choices or not isinstance(input_spec, dict):
            raise ElicitationError(f"{prompt_id}: text selection needs input and no choices")
        for field in ("id", "label", "event"):
            if not isinstance(input_spec.get(field), str) or not input_spec[field]:
                raise ElicitationError(f"{prompt_id}: input needs {field}")
    elif not choices and choice_source is None:
        raise ElicitationError(f"{prompt_id}: at least one static choice is required")
    minimum = prompt.get("minimum_selected", 1)
    if not isinstance(minimum, int) or minimum < 1:
        raise ElicitationError(f"{prompt_id}: minimum_selected must be at least 1")
    raw_template_fields = prompt.get("template_fields", [])
    if not isinstance(raw_template_fields, list) or any(
        not isinstance(field, str) or not field for field in raw_template_fields
    ):
        raise ElicitationError(f"{prompt_id}: template_fields must be non-empty strings")
    template_fields = tuple(raw_template_fields)
    placeholders = tuple(
        field_name
        for _, field_name, _, _ in string.Formatter().parse(text)
        if field_name is not None
    )
    if set(placeholders) != set(template_fields):
        raise ElicitationError(
            f"{prompt_id}: question placeholders must match template_fields exactly"
        )
    return Question(
        prompt_id,
        text.strip(),
        selection,
        tuple(choices),
        minimum,
        input_spec.get("id") if isinstance(input_spec, dict) else None,
        input_spec.get("label") if isinstance(input_spec, dict) else None,
        input_spec.get("event") if isinstance(input_spec, dict) else None,
        template_fields,
        choice_source,
    )


def _context_value(context: Mapping[str, Any], dotted: str) -> str:
    value: object = context
    for segment in dotted.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            raise ElicitationError(f"missing prompt template field {dotted!r}")
        value = value[segment]
    if not isinstance(value, str) or not value:
        raise ElicitationError(f"prompt template field {dotted!r} must be a non-empty string")
    return value


def _context_object(context: Mapping[str, Any], dotted: str) -> object:
    value: object = context
    for segment in dotted.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            raise ElicitationError(f"missing dynamic choice context {dotted!r}")
        value = value[segment]
    return value


def _dynamic_choices(source: ChoiceSource, context: Mapping[str, Any]) -> tuple[Choice, ...]:
    raw_choices = _context_object(context, source.context)
    if not isinstance(raw_choices, list):
        raise ElicitationError(f"dynamic choice context {source.context!r} must be an array")
    choices: list[Choice] = []
    seen: set[str] = set()
    for raw in raw_choices:
        if not isinstance(raw, Mapping):
            raise ElicitationError(f"dynamic choice context {source.context!r} is malformed")
        fields = (source.id_field, source.label_field, source.description_field)
        if any(not isinstance(raw.get(field), str) or not raw[field] for field in fields):
            raise ElicitationError(f"dynamic choice context {source.context!r} is malformed")
        choice_id = raw[source.id_field]
        if choice_id in seen:
            raise ElicitationError(f"dynamic choice id {choice_id!r} is duplicated")
        seen.add(choice_id)
        recommended = False
        if source.recommended_field is not None:
            raw_recommended = raw.get(source.recommended_field)
            if not isinstance(raw_recommended, bool):
                raise ElicitationError(
                    f"dynamic choice recommended field {source.recommended_field!r} "
                    "must be boolean"
                )
            recommended = raw_recommended
        value = raw.get(source.value_source_field)
        if not isinstance(value, str) or not value:
            raise ElicitationError(f"dynamic choice {choice_id!r} has no string value")
        choices.append(
            Choice(
                id=choice_id,
                label=raw[source.label_field],
                description=raw[source.description_field],
                event=source.event,
                recommended=recommended,
                value_field=source.value_field,
                value=value,
            )
        )
    return tuple(choices)


def resolve_question(question: Question, context: Mapping[str, Any]) -> Question:
    """Resolve only placeholders explicitly declared by the prompt contract."""

    if not question.template_fields and question.choice_source is None:
        return question
    values = {field: _context_value(context, field) for field in question.template_fields}
    text = question.text
    for field, value in values.items():
        text = text.replace("{" + field + "}", value)
    return Question(
        id=question.id,
        text=text,
        selection=question.selection,
        choices=(
            (*_dynamic_choices(question.choice_source, context), *question.choices)
            if question.choice_source is not None
            else question.choices
        ),
        minimum_selected=question.minimum_selected,
        input_id=question.input_id,
        input_label=question.input_label,
        input_event=question.input_event,
        template_fields=(),
        choice_source=None,
    )


def native_payload(
    question: Question, harness: str, context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if question.template_fields or question.choice_source is not None:
        if context is None:
            raise ElicitationError("templated question requires controller context")
        question = resolve_question(question, context)
    surface = NATIVE_SURFACES.get(harness.casefold(), "structured_elicitation")
    return {
        "surface": surface,
        "prompt_id": question.id,
        "question": question.text,
        "selection": question.selection,
        "minimum_selected": question.minimum_selected,
        "choices": [_native_choice(choice) for choice in question.choices],
        "input": (
            {
                "id": question.input_id,
                "label": question.input_label,
                "event": question.input_event,
            }
            if question.selection == "text"
            else None
        ),
    }


def _native_choice(choice: Choice) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": choice.id,
        "label": choice.label,
        "description": choice.description,
        "event": choice.event,
        "recommended": choice.recommended,
    }
    if choice.value_field is not None and choice.value is not None:
        payload["payload"] = {choice.value_field: choice.value}
    return payload


def markdown_fallback(
    question: Question, context: Mapping[str, Any] | None = None
) -> str:
    if question.template_fields or question.choice_source is not None:
        if context is None:
            raise ElicitationError("templated question requires controller context")
        question = resolve_question(question, context)
    if question.selection == "text":
        assert question.input_label is not None
        return f"{question.text}\n\nReply with {question.input_label.casefold()}."
    lines = [question.text, ""]
    for index, choice in enumerate(question.choices, 1):
        recommendation = " *(Recommended)*" if choice.recommended else ""
        lines.append(f"{index}. **{choice.label}**{recommendation} — {choice.description}")
    instruction = (
        "Reply with one number."
        if question.selection == "single"
        else "Reply with one or more comma-separated numbers."
    )
    return "\n".join([*lines, "", instruction])


def load_question(path: Path, prompt_id: str) -> Question:
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ElicitationError(f"cannot load prompt specification: {error}") from error
    prompts = document.get("prompts") if isinstance(document, dict) else None
    if not isinstance(prompts, dict) or not isinstance(prompts.get(prompt_id), dict):
        raise ElicitationError(f"unknown prompt id {prompt_id!r}")
    return parse_question(prompt_id, prompts[prompt_id])


def main(prompts_path: Path, arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_id")
    parser.add_argument("--harness", default="codex")
    parser.add_argument("--format", choices=("native", "markdown"), default="native")
    parser.add_argument("--check", action="store_true", help="validate without rendering")
    parser.add_argument("--context-json", help="logical controller context for prompt templates")
    args = parser.parse_args(arguments)
    try:
        question = load_question(prompts_path, args.prompt_id)
    except ElicitationError as error:
        parser.error(str(error))
    context = None
    if args.context_json:
        try:
            context = json.loads(args.context_json)
        except json.JSONDecodeError as error:
            parser.error(f"--context-json must be valid JSON: {error}")
        if not isinstance(context, dict):
            parser.error("--context-json must decode to an object")
    if args.check:
        if (
            not question.template_fields and question.choice_source is None
        ) or context is not None:
            native_payload(question, args.harness, context)
            markdown_fallback(question, context)
        return 0
    if args.format == "markdown":
        print(markdown_fallback(question, context))
    else:
        print(json_text(native_payload(question, args.harness, context)))
    return 0
