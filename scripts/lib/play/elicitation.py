"""Harness-neutral structured elicitation contracts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .render import json_text


class ElicitationError(ValueError):
    pass


NATIVE_SURFACES = {
    "codex": "request_user_input",
    "claude": "askquestion",
    "kimi": "askquestion",
}


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    description: str
    event: str
    recommended: bool = False


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
    if selection == "text":
        if choices or not isinstance(input_spec, dict):
            raise ElicitationError(f"{prompt_id}: text selection needs input and no choices")
        for field in ("id", "label", "event"):
            if not isinstance(input_spec.get(field), str) or not input_spec[field]:
                raise ElicitationError(f"{prompt_id}: input needs {field}")
    elif not choices:
        raise ElicitationError(f"{prompt_id}: at least one static choice is required")
    minimum = prompt.get("minimum_selected", 1)
    if not isinstance(minimum, int) or minimum < 1:
        raise ElicitationError(f"{prompt_id}: minimum_selected must be at least 1")
    return Question(
        prompt_id,
        text.strip(),
        selection,
        tuple(choices),
        minimum,
        input_spec.get("id") if isinstance(input_spec, dict) else None,
        input_spec.get("label") if isinstance(input_spec, dict) else None,
        input_spec.get("event") if isinstance(input_spec, dict) else None,
    )


def native_payload(question: Question, harness: str) -> dict[str, Any]:
    surface = NATIVE_SURFACES.get(harness.casefold(), "structured_elicitation")
    return {
        "surface": surface,
        "prompt_id": question.id,
        "question": question.text,
        "selection": question.selection,
        "minimum_selected": question.minimum_selected,
        "choices": [
            {
                "id": choice.id,
                "label": choice.label,
                "description": choice.description,
                "event": choice.event,
                "recommended": choice.recommended,
            }
            for choice in question.choices
        ],
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


def markdown_fallback(question: Question) -> str:
    if question.selection == "text":
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
    args = parser.parse_args(arguments)
    try:
        question = load_question(prompts_path, args.prompt_id)
    except ElicitationError as error:
        parser.error(str(error))
    if args.check:
        native_payload(question, args.harness)
        markdown_fallback(question)
        return 0
    if args.format == "markdown":
        print(markdown_fallback(question))
    else:
        print(json_text(native_payload(question, args.harness)))
    return 0
