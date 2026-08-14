"""Validation for the declarative Play controller bundle."""

from __future__ import annotations

import json
import string
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .executors import action_executor


class MachineValidationError(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__(f"machine validation failed with {len(errors)} error(s)")
        self.errors = errors


@dataclass(frozen=True)
class ValidationSummary:
    states: int
    transitions: int
    actions: int
    prompts: int

    def render(self) -> str:
        return (
            f"validated {self.states} states, {self.transitions} transitions, "
            f"{self.actions} actions, {self.prompts} prompts"
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise MachineValidationError([f"{path.name}: invalid YAML: {error}"]) from error
    if not isinstance(payload, dict):
        raise MachineValidationError([f"{path.name}: root must be an object"])
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise MachineValidationError([f"{path.name}: invalid JSON: {error}"]) from error
    if not isinstance(payload, dict):
        raise MachineValidationError([f"{path.name}: root must be an object"])
    return payload


def _target(states: dict, state: str, event: str, branch: int = 0) -> str | None:
    try:
        return states[state]["on"][event][branch]["target"]
    except (KeyError, IndexError, TypeError):
        return None


def validate_bundle(
    root: Path,
    *,
    documents: dict[str, dict[str, Any]] | None = None,
) -> ValidationSummary:
    controller = root / "references" / "controller"
    if documents is None:
        machine = _load_yaml(controller / "machine.yaml")
        actions_doc = _load_yaml(controller / "actions.yaml")
        prompts_doc = _load_yaml(controller / "prompts.yaml")
    else:
        try:
            machine = documents["machine"]
            actions_doc = documents["actions"]
            prompts_doc = documents["prompts"]
        except KeyError as error:
            raise MachineValidationError(
                [f"controller documents are missing {error.args[0]!r}"]
            ) from error
    machine_schema = (
        documents.get("machine_schema")
        if documents is not None
        else _load_json(controller / "machine.schema.json")
    )
    context_schema = (
        documents.get("context_schema")
        if documents is not None
        else _load_json(controller / "context.schema.json")
    )
    handoff_schema = (
        documents.get("handoff_schema")
        if documents is not None
        else _load_json(controller / "handoff.schema.json")
    )
    if not isinstance(machine_schema, dict):
        raise MachineValidationError(["machine schema document is missing or invalid"])
    if not isinstance(context_schema, dict):
        raise MachineValidationError(["context schema document is missing or invalid"])
    if not isinstance(handoff_schema, dict):
        raise MachineValidationError(["controller schema documents are missing or invalid"])
    errors: list[str] = []

    for error in sorted(
        Draft202012Validator(machine_schema).iter_errors(machine),
        key=lambda item: [str(part) for part in item.absolute_path],
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "machine"
        errors.append(f"machine.yaml:{location}: {error.message}")

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    check(machine.get("schema") == "play.machine/v1", "machine schema must be play.machine/v1")
    check(actions_doc.get("schema") == "play.actions/v1", "action schema must be play.actions/v1")
    check(prompts_doc.get("schema") == "play.prompts/v1", "prompt schema must be play.prompts/v1")
    check(str(machine_schema.get("$id", "")).endswith("play.machine.v1.json"), "machine schema id is invalid")
    check(str(context_schema.get("$id", "")).endswith("play.context.v1.json"), "context schema id is invalid")
    check(str(handoff_schema.get("$id", "")).endswith("play.handoff.v1.json"), "handoff schema id is invalid")

    states = machine.get("states", {})
    actions = actions_doc.get("actions", {})
    prompts = prompts_doc.get("prompts", {})
    initial_value = machine.get("initial")
    initial = initial_value if isinstance(initial_value, str) else ""
    terminals = set(machine.get("terminal", []))
    owners = set(actions_doc.get("owners", []))
    effects = set(actions_doc.get("effects", []))
    specialist_owners = actions_doc.get("specialist_owners", [])
    adapter_specialist_owners = actions_doc.get("adapter_specialist_owners", [])
    route_owners = actions_doc.get("route_owners", {})
    guards = set(actions_doc.get("guards", []))
    mutations = set(actions_doc.get("mutations", []))
    failure_event = actions_doc.get("failure_event", {}).get("id")
    expected_specialists = [
        "rote-using-adapters",
        "rote-shell",
        "rote-browse",
        "rote-workspace",
    ]
    check(
        handoff_schema.get("$defs", {}).get("specialistOwner", {}).get("enum")
        == expected_specialists,
        "handoff schema must use the closed Rote specialist set",
    )
    check(
        specialist_owners == expected_specialists,
        "delegated Explore owners must be the closed Rote specialist set",
    )
    check(
        adapter_specialist_owners == ["rote-adapter-create", "rote-adapter-config"],
        "CALL adapter convergence must use the closed Rote create/config specialist set",
    )
    check(
        route_owners
        == {
            "call": "rote-using-adapters",
            "shell": "rote-shell",
            "drive": "rote-browse",
            "combined": "rote-workspace",
        },
        "every exploration route must map to its exact Rote specialist",
    )
    check(isinstance(initial_value, str), "initial state must be a string")
    check(initial in states, f"initial state {initial_value!r} is missing")
    check(bool(terminals), "at least one terminal state is required")
    for terminal in terminals:
        check(terminal in states, f"terminal state {terminal!r} is missing")

    state_keys = {"owner", "checkpoint", "requires", "entry", "prompt", "on"}
    transition_keys = {"guard", "target", "mutate"}
    edges: dict[str, set[str]] = defaultdict(set)
    predecessors: dict[str, set[str]] = defaultdict(set)

    for state_name, state in states.items():
        if not isinstance(state, dict):
            errors.append(f"{state_name}: state must be an object")
            continue
        unknown = set(state) - state_keys
        check(not unknown, f"{state_name}: unknown state keys {', '.join(sorted(unknown))}")
        check(state.get("owner") in owners, f"{state_name}: invalid owner {state.get('owner')!r}")
        if state_name in terminals:
            check(set(state) <= {"owner"}, f"{state_name}: terminal states may declare only owner")
            continue
        entry = state.get("entry")
        prompt_name = state.get("prompt")
        check(sum(value is not None for value in (entry, prompt_name)) == 1,
              f"{state_name}: declare exactly one entry action or prompt")
        check(state.get("checkpoint") in {"before", "after", "both"},
              f"{state_name}: checkpoint must be before, after, or both")
        handled = state.get("on", {})
        check(isinstance(handled, dict) and bool(handled), f"{state_name}: must declare handled events")
        expected: set[str] | None = None
        if isinstance(entry, dict):
            action_name = entry.get("action")
            action = actions.get(action_name)
            check(action is not None, f"{state_name}: action {action_name!r} is not declared")
            if isinstance(action, dict):
                check(action.get("owner") == state.get("owner"), f"{state_name}: owner differs from action {action_name}")
                check(action.get("effect") in effects, f"{state_name}: action {action_name} has invalid effect")
                if action.get("effect") != "none":
                    check(state.get("checkpoint") == "both", f"{state_name}: effectful action {action_name} requires checkpoint both")
                event_map = action.get("events_by_state", {}).get(state_name) or action.get("events") or {}
                expected = set(event_map) | ({failure_event} if failure_event else set())
        elif isinstance(prompt_name, str):
            prompt = prompts.get(prompt_name)
            check(prompt is not None, f"{state_name}: prompt {prompt_name!r} is not declared")
            if isinstance(prompt, dict):
                expected = set(prompt.get("events", {}))
        if expected is not None and isinstance(handled, dict):
            actual = set(handled)
            check(not expected - actual, f"{state_name}: missing events {', '.join(sorted(expected - actual))}")
            check(not actual - expected, f"{state_name}: undeclared events {', '.join(sorted(actual - expected))}")
        if not isinstance(handled, dict):
            continue
        for event, branches in handled.items():
            check(isinstance(branches, list) and bool(branches), f"{state_name}.{event}: needs a transition")
            if not isinstance(branches, list) or not branches:
                continue
            unconditional = [index for index, branch in enumerate(branches) if not branch.get("guard")]
            guarded = [index for index, branch in enumerate(branches) if branch.get("guard")]
            if guarded:
                check(unconditional == [len(branches) - 1], f"{state_name}.{event}: guarded branches require one final fallback")
            else:
                check(len(branches) == 1, f"{state_name}.{event}: unguarded events require exactly one transition")
            for transition in branches:
                unknown_transition = set(transition) - transition_keys
                check(not unknown_transition, f"{state_name}.{event}: unknown transition keys {', '.join(sorted(unknown_transition))}")
                target = transition.get("target")
                check(target in states, f"{state_name}.{event}: target {target!r} is missing")
                check(transition.get("mutate") in mutations, f"{state_name}.{event}: mutation {transition.get('mutate')!r} is not declared")
                guard = transition.get("guard")
                if guard:
                    check(guard in guards, f"{state_name}.{event}: guard {guard!r} is not declared")
                if target in states:
                    edges[state_name].add(target)
                    predecessors[target].add(state_name)

    for name, action in actions.items():
        check(action.get("owner") in owners, f"action {name}: invalid owner")
        check(action.get("effect") in effects, f"action {name}: invalid effect")
        check(sum(key in action for key in ("events", "events_by_state")) == 1,
              f"action {name}: declare events or events_by_state")
        if action.get("kind") == "delegated":
            specialist = action.get("specialist")
            specialist_from = action.get("specialist_from")
            check(
                (isinstance(specialist, str) and not specialist_from)
                or (specialist is None and specialist_from == "execution.owner"),
                f"action {name}: delegated actions require one exact specialist source",
            )
            allowed_specialists = {
                *expected_specialists,
                *adapter_specialist_owners,
                "rote-setup",
                "rote-registry",
                "rote-flow-crystallization",
                "rote-flow-authoring",
                "rote-flow-run",
                "rote-org",
            }
            if isinstance(specialist, str):
                check(
                    specialist in allowed_specialists,
                    f"action {name}: unknown specialist {specialist}",
                )

    for name, prompt in prompts.items():
        question = prompt.get("question")
        check(isinstance(question, str) and question.strip().endswith("?"),
              f"prompt {name}: question must be a non-empty question ending in ?")
        template_fields = prompt.get("template_fields", [])
        check(
            isinstance(template_fields, list)
            and all(isinstance(field, str) and field for field in template_fields),
            f"prompt {name}: template_fields must be non-empty strings",
        )
        placeholders = (
            [
                field_name
                for _, field_name, _, _ in string.Formatter().parse(question)
                if field_name is not None
            ]
            if isinstance(question, str)
            else []
        )
        check(
            set(placeholders) == set(template_fields) if isinstance(template_fields, list) else False,
            f"prompt {name}: question placeholders must match template_fields exactly",
        )
        selection = prompt.get("selection")
        check(selection in {"single", "multiple", "text"},
              f"prompt {name}: selection must be single, multiple, or text")
        choices = prompt.get("choices", [])
        if selection == "text":
            check(isinstance(choices, list) and not choices, f"prompt {name}: text selection must not declare choices")
        else:
            check(isinstance(choices, list) and bool(choices), f"prompt {name}: must declare at least one static choice")
        declared = set(prompt.get("events", {}))
        presented: set[str] = set()
        if isinstance(choices, list):
            for choice in choices:
                for field in ("id", "label", "description", "event"):
                    check(isinstance(choice.get(field), str) and bool(choice.get(field)),
                          f"prompt {name}: every choice needs {field}")
                if choice.get("event"):
                    presented.add(choice["event"])
        source = prompt.get("choices_from")
        if isinstance(source, dict):
            for field in (
                "context",
                "id_field",
                "label_field",
                "description_field",
                "value_source_field",
                "value_field",
                "event",
            ):
                check(isinstance(source.get(field), str) and bool(source.get(field)),
                      f"prompt {name}: choices_from needs {field}")
            if source.get("event"):
                presented.add(source["event"])
        input_spec = prompt.get("input")
        if selection == "text":
            check(isinstance(input_spec, dict), f"prompt {name}: text selection needs input")
            if isinstance(input_spec, dict):
                for field in ("id", "label", "event"):
                    check(isinstance(input_spec.get(field), str) and bool(input_spec.get(field)),
                          f"prompt {name}: input needs {field}")
                if input_spec.get("event"):
                    presented.add(input_spec["event"])
        check(presented == declared, f"prompt {name}: presented choices must cover exactly its declared events")
        if selection == "multiple":
            minimum = prompt.get("minimum_selected")
            check(isinstance(minimum, int) and minimum >= 1,
                  f"prompt {name}: multiple selection needs minimum_selected >= 1")

    context_roots = set(context_schema.get("required", []))
    for name, action in actions.items():
        timeout_seconds = action.get("timeout_seconds", 120)
        check(
            isinstance(timeout_seconds, int)
            and not isinstance(timeout_seconds, bool)
            and 1 <= timeout_seconds <= 3600,
            f"action {name}: timeout_seconds must be an integer from 1 to 3600",
        )
        for required in action.get("input_required", []):
            root_name = required.split(".", 1)[0]
            check(root_name in context_roots,
                  f"action {name}: input root {root_name!r} is absent from durable context")
        executor = action_executor(name, action)
        check(
            executor is not None,
            f"action {name}: has no closed executor; deterministic commands must use scripts/bin, commandless actions need a runtime handler, and external work must be delegated",
        )
        if executor == "specialist":
            check(
                isinstance(action.get("specialist"), str)
                or action.get("specialist_from") == "execution.owner",
                f"action {name}: specialist executor is not exactly bound",
            )

    reachable = {initial}
    queue = deque([initial])
    while queue:
        state = queue.popleft()
        for target in edges[state]:
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    unreachable = set(states) - reachable
    check(not unreachable, f"unreachable states: {', '.join(sorted(unreachable))}")

    can_terminate = set(terminals)
    queue = deque(terminals)
    while queue:
        state = queue.popleft()
        for source in predecessors[state]:
            if source not in can_terminate:
                can_terminate.add(source)
                queue.append(source)
    nonterminating = set(states) - can_terminate
    check(not nonterminating, f"states without a terminal path: {', '.join(sorted(nonterminating))}")

    all_states = set(states)
    dominators = {state: ({initial} if state == initial else set(all_states)) for state in states}
    while True:
        changed = False
        for state in set(states) - {initial}:
            incoming = predecessors[state]
            common = set.intersection(*(dominators[source] for source in incoming)) if incoming else set()
            value = common | {state}
            if value != dominators[state]:
                dominators[state] = value
                changed = True
        if not changed:
            break
    rules = {
        "use_auth_repair_offer": (
            "use_auth_repair_handoff",
            "use_auth_repair_execute",
            "use_auth_repair_receipt",
        ),
        "use_auth_repair_handoff": ("use_auth_repair_execute", "use_auth_repair_receipt"),
        "use_auth_repair_execute": ("use_auth_repair_receipt",),
        "save_judge": ("crystallize",),
        "crystallize": ("save_prepare", "save_offer", "public_owner_offer", "author_release", "birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "save_prepare": ("save_offer", "public_owner_offer", "author_release", "birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "save_offer": ("public_owner_offer", "author_release", "birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "author_release": ("birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "birth_capture": ("private_publish", "public_publish", "birth_bind", "index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "birth_bind": ("index", "saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "index": ("saved_inspect", "publication_credentials", "publication_smoke", "birth_present"),
        "saved_inspect": ("publication_credentials", "publication_smoke", "birth_present"),
        "publication_credentials": ("publication_smoke",),
    }
    for dominator, governed in rules.items():
        for state in governed:
            if state in states:
                check(dominator in dominators[state], f"{dominator} must dominate {state}")

    check(_target(states, "qualify", "exact_play_request") == "use_inspect", "an exact Play request must enter read-only inspection")
    check(_target(states, "qualify", "play_search_request") == "search", "an explicit Play search must use the unified search action")
    check(_target(states, "search", "search_ready") == "search_present", "a search-only request must present results before selection")
    check(_target(states, "search_present", "search_presented") == "search_offer", "presented search results must offer read-only inspection")
    check(_target(states, "classify", "full_match") == "use_inspect", "an adequate discovered Play must enter read-only inspection")
    check(states.get("use_inspect", {}).get("entry", {}).get("action") == "inspect_registry_play", "Use must start with reusable Play inspection")
    check(_target(states, "use_inspect", "play_inspected") == "use_decide", "inspection must route by local readiness")
    check(states.get("use_decide", {}).get("entry", {}).get("action") == "route_inspected_play", "local readiness must be resolved deterministically")
    check(_target(states, "use_decide", "local_play_ready") == "use_prepare", "an exact local Play must prepare its run handoff without a pull prompt")
    check(_target(states, "use_decide", "remote_pull_required") == "use_offer", "a remote Play must reach pull consent")
    check(states.get("use_offer", {}).get("prompt") == "approve_play_run", "remote Use must ask for pull and execution approval")
    check(_target(states, "use_offer", "play_run_approved") == "use_prepare", "an approved remote Play must prepare its run handoff")
    check(states.get("use_prepare", {}).get("entry", {}).get("action") == "prepare_play_run_handoff", "Play execution must bind a typed run handoff")
    check(_target(states, "use_prepare", "play_run_handoff_ready") == "use_run", "only a prepared run handoff may enter execution")
    check(states.get("use_run", {}).get("entry", {}).get("action") == "run_registry_play", "Use mode must be owned by run_registry_play")
    check(actions.get("inspect_registry_play", {}).get("command") == "scripts/bin/play-inspect <match.reference> --json", "Use inspection must invoke the reusable first-class wrapper")
    check(
        actions.get("run_registry_play", {}).get("kind") == "deterministic"
        and actions.get("run_registry_play", {}).get("command")
        == "scripts/bin/play-run --stdin --json",
        "Use mode must invoke the universal deterministic Play runner",
    )
    check(
        states.get("use_verify", {}).get("entry", {}).get("action")
        == "verify_play_output",
        "Use output verification must remain deterministic",
    )
    check(actions.get("inspect_saved_play", {}).get("command") == "scripts/bin/play-inspect <publication.canonical_reference> --json", "saved Play readback must invoke the reusable first-class wrapper")
    check(initial == "invoke", "the typed invocation classifier must be the initial state")
    check(
        actions.get("classify_play_invocation", {}).get("command")
        == "scripts/bin/play-onboarding classify --stdin --json",
        "Play invocation aliases and URIs must use the deterministic classifier",
    )
    check(
        _target(states, "invoke", "empty_play_invocation") == "onboarding_probe",
        "an empty Play invocation must enter live onboarding",
    )
    check(
        _target(states, "invoke", "play_uri_invocation") == "onboarding_probe",
        "a canonical Play URI must enter live onboarding",
    )
    check(
        _target(states, "invoke", "ordinary_play_invocation") == "qualify",
        "ordinary requests must preserve normal Play qualification",
    )
    check(
        _target(states, "invoke", "outcome_play_invocation") == "search",
        "unambiguous outcomes must bypass model qualification",
    )
    check(
        _target(states, "use_decide", "play_parameter_required")
        == "use_parameter_offer",
        "missing required Play parameters must reach typed elicitation",
    )
    check(
        actions.get("probe_rote_for_onboarding", {}).get("command")
        == "scripts/bin/play-onboarding probe --json",
        "onboarding must probe the live Rote binary before invoking it",
    )
    check(
        _target(states, "onboarding_probe", "rote_available") == "onboarding_identity"
        and _target(states, "onboarding_probe", "rote_available", 1) == "use_inspect",
        "installed Rote must route greeting to identity and URI to first-class inspection",
    )
    check(
        _target(states, "onboarding_probe", "rote_missing") == "onboarding_setup"
        and _target(states, "onboarding_probe", "rote_missing", 1)
        == "onboarding_card_fetch",
        "missing Rote must route greeting to setup and URI to its public card",
    )
    check(
        actions.get("inspect_onboarding_identity", {}).get("command")
        == "scripts/bin/play-onboarding identity --stdin --json",
        "the greeting identity must come from the typed whoami reader",
    )
    check(
        _target(states, "onboarding_identity", "onboarding_identity_setup_required")
        == "onboarding_setup",
        "an installed but unauthenticated Rote must enter setup",
    )
    check(
        _target(states, "onboarding_identity", "onboarding_identity_ready")
        == "onboarding_experience"
        and _target(states, "onboarding_experience", "onboarding_first_use")
        == "onboarding_first_present"
        and _target(states, "onboarding_experience", "onboarding_returning")
        == "onboarding_welcome",
        "authenticated greetings must split typed first-use and returning paths",
    )
    check(
        actions.get("inspect_onboarding_experience", {}).get("command")
        == "scripts/bin/play-onboarding experience --stdin --json"
        and actions.get("remember_first_use_orientation", {}).get("effect")
        == "local-write"
        and _target(
            states, "onboarding_first_record", "onboarding_first_use_recorded"
        )
        == "onboarding_first_offer",
        "first-use orientation must be presented before its private marker is written",
    )
    check(
        states.get("onboarding_first_offer", {}).get("prompt")
        == "choose_first_use_path"
        and _target(
            states, "onboarding_first_offer", "onboarding_starter_selected"
        )
        == "use_inspect"
        and _target(
            states, "onboarding_first_offer", "onboarding_awareness_selected"
        )
        == "awareness_collect",
        "first use must offer the pinned inspected starter, a goal, awareness, or dismissal",
    )
    check(
        _target(states, "use_receipt", "receipt_ready")
        == "onboarding_activation_present"
        and states.get("onboarding_activation_offer", {}).get("prompt")
        == "choose_onboarding_next",
        "a verified starter receipt must explain activation before the next choice",
    )
    check(
        _target(states, "onboarding_setup", "rote_setup_completed") == "onboarding_probe",
        "completed setup must be independently reprobed",
    )
    setup_policy = " ".join(actions.get("handoff_rote_setup", {}).get("command_policy", []))
    check(
        "Invoke the rote-setup skill" in setup_policy
        and "Do not run an installer" in setup_policy
        and "improvised curl installer" in setup_policy,
        "Play onboarding must preserve rote-setup ownership and installer approval",
    )
    card_policy = " ".join(
        actions.get("fetch_onboarding_play_card", {}).get("command_policy", [])
    )
    check(
        actions.get("fetch_onboarding_play_card", {}).get("command")
        == "scripts/bin/play-onboarding card --stdin --json"
        and "only canonical HTTPS play.modiqo.ai" in card_policy
        and "never execute an install or run action" in card_policy,
        "the no-Rote URI fallback must be a bounded read-only card fetch",
    )
    welcome_prompt = prompts.get("welcome_play_request", {})
    check(
        welcome_prompt.get("question")
        == "How are you, {onboarding.email_handle}? What can I help you with?"
        and welcome_prompt.get("template_fields") == ["onboarding.email_handle"],
        "the warm greeting must bind the typed whoami email handle",
    )
    first_prompt = prompts.get("choose_first_use_path", {})
    first_choices = {
        choice.get("id"): choice for choice in first_prompt.get("choices", [])
    }
    check(
        first_prompt.get("question") == "What would you like to do first?"
        and first_choices.get("hello", {}).get("recommended") is True
        and first_choices.get("done", {}).get("event") == "onboarding_dismissed",
        "first use must recommend inspection of Hello while preserving a clear dismissal",
    )
    check(actions.get("search_authorized_plays", {}).get("command") == "scripts/bin/play-search <request.intent> --limit 5 --json", "Play discovery must invoke the bounded local and registry search")
    check(_target(states, "qualify", "play_awareness_request") == "awareness_collect", "an awareness request must enter the digest path")
    check(actions.get("collect_awareness_digest", {}).get("effect") == "local-write", "awareness collection may write only remembered local state")
    check(actions.get("collect_awareness_digest", {}).get("command") == "scripts/bin/play-digest --remember --days <awareness.window_days> --json", "awareness must invoke the remembered digest command")
    check(_target(states, "awareness_collect", "awareness_unchanged") == "completed", "unchanged awareness must finish without an action prompt")
    check(_target(states, "awareness_offer", "awareness_play_selected") == "use_inspect", "an exact awareness selection must enter inspection")
    check(_target(states, "qualify", "play_creation_request") == "creator_search", "explicit creator intent must search before exploration")
    check(
        _target(states, "creator_classify", "creator_no_match") == "standby_exit",
        "creator intent without a match must apply the pre-work capture decision and step aside",
    )
    check(
        _target(states, "invoke", "settled_task_invocation") == "save_judge",
        "a settled-task re-entry must reach the save-worthiness judge directly",
    )
    check(
        _target(states, "classify", "no_match") == "standby_exit"
        and _target(states, "classify", "partial_match") == "standby_exit"
        and _target(states, "classify", "uncertain_match") == "standby_exit",
        "inadequate discovery must exit to standby instead of orchestrating exploration",
    )
    check(
        _target(states, "qualify", "play_excluded") == "standby_exit",
        "an explicit exclusion must pass the preference recorder before exiting",
    )
    check(
        states.get("standby_exit", {}).get("entry", {}).get("action") == "record_standby"
        and _target(states, "standby_exit", "standby_recorded") == "exited",
        "standby must record the capture/normal decision and scoped preferences, then exit",
    )
    check(
        actions.get("record_standby", {}).get("command")
        == "scripts/bin/play-standby record --stdin --json",
        "the capture decision and preference ledger must use the deterministic standby recorder",
    )
    check(
        states.get("save_judge", {}).get("entry", {}).get("action")
        == "judge_save_worthiness"
        and actions.get("judge_save_worthiness", {}).get("kind") == "evaluator"
        and _target(states, "save_judge", "worth_saving") == "crystallize"
        and _target(states, "save_judge", "not_worth_saving") == "exited",
        "save worthiness must be judged from trace evidence and route only to crystallization or a quiet exit",
    )
    check(
        predecessors["crystallize"] == {"save_judge"},
        "crystallization may follow only an affirmative save-worthiness judgment",
    )
    for forbidden in ("use_preflight", "use_resolve"):
        check(forbidden not in states, f"{forbidden} must stay inside the rote play run controller")
    check(
        predecessors["use_prepare"] == {"use_decide", "use_offer"},
        "run handoff preparation may follow only local readiness or remote pull approval",
    )
    check(predecessors["use_run"] == {"use_prepare"}, "execution may follow only a prepared run handoff")
    check("use_inspect" in dominators["use_run"], "inspection must dominate execution")
    check(_target(states, "use_run", "play_run_ready") == "use_verify", "successful execution must pass unchanged output directly to verification")
    check(predecessors["use_verify"] == {"use_run"}, "Use verification may follow only successful Play execution")
    receipt_policy = " ".join(actions.get("build_receipt", {}).get("command_policy", []))
    check(
        "Preserve output.primary exactly as received" in receipt_policy
        and "never wrap, summarize, convert, or decorate it" in receipt_policy,
        "Use receipts must preserve the Play output for harness-owned presentation",
    )
    check(predecessors["birth_bind"] == {"private_publish", "public_publish"}, "birth binding may follow only successful private or public publication")
    check(predecessors["index"] == {"birth_bind"}, "index may follow only successful birth binding")
    check(predecessors["saved_inspect"] == {"index"}, "saved inspection may follow only successful indexing")
    check(predecessors["publication_credentials"] == {"saved_inspect"}, "public credential validation may follow only successful canonical inspection")
    check(predecessors["publication_smoke"] == {"publication_credentials"}, "public smoke may follow only verified credential contracts")
    check(predecessors["birth_present"] == {"saved_inspect", "publication_smoke"}, "birth certificate presentation must follow private readback or verified public smoke")
    check(
        _target(states, "saved_inspect", "saved_play_inspected") == "publication_credentials",
        "a matching public inspection must enter associated credential validation",
    )
    check(
        _target(states, "saved_inspect", "saved_play_inspected", 1) == "birth_present",
        "a matching private inspection may enter verified birth certificate presentation",
    )
    check(
        _target(states, "publication_credentials", "associated_credentials_verified")
        == "publication_smoke",
        "verified associated credential contracts must enter canonical public smoke",
    )
    check(
        _target(states, "publication_smoke", "public_smoke_verified") == "birth_present",
        "public certificate presentation may follow only a verified canonical smoke run",
    )
    birth_presented = states.get("birth_present", {}).get("on", {}).get(
        "birth_certificate_presented", []
    )
    check(
        isinstance(birth_presented, list)
        and len(birth_presented) == 2
        and birth_presented[0].get("guard") == "save_choice_private"
        and birth_presented[0].get("target") == "team_invite_offer"
        and birth_presented[1].get("target") == "completed",
        "a saved Play may offer team invites only after its verified birth certificate",
    )
    check(
        predecessors["team_invite_offer"]
        == {"onboarding_team_present", "team_invite_execute", "birth_present"},
        "team invites must follow team creation, another invite, or verified private publication",
    )
    check(
        _target(states, "crystallize", "candidate_ready") == "save_prepare"
        and predecessors["save_prepare"] == {"crystallize"}
        and predecessors["save_offer"] == {"save_prepare"},
        "verified candidates must resolve public namespaces before the save choice",
    )
    check(
        _target(states, "save_prepare", "public_owner_context_ready") == "save_offer"
        and _target(states, "save_prepare", "public_owner_context_unavailable")
        == "save_offer"
        and actions.get("resolve_public_owner", {}).get("command")
        == "scripts/bin/play-public-owner --json",
        "pre-save owner resolution must use the typed read-only namespace probe",
    )
    check(
        _target(states, "save_offer", "save_public") == "author_release"
        and states.get("save_offer", {}).get("on", {}).get("save_public", [{}])[0].get("guard")
        == "public_owner_is_resolved"
        and _target(states, "save_offer", "save_public", 1) == "public_owner_offer"
        and states.get("save_offer", {}).get("on", {}).get("save_public", [{}, {}])[1].get("guard")
        == "public_owner_choice_is_required"
        and _target(states, "save_offer", "save_public", 2) == "blocked"
        and _target(states, "public_owner_offer", "public_owner_selected")
        == "author_release",
        "Public must bind a resolved or selected namespace before release",
    )
    check(
        _target(states, "birth_capture", "birth_captured", 1) == "public_publish"
        and "public_owner" not in states,
        "post-release birth capture must not re-run public owner resolution",
    )
    check(
        _target(states, "author_release", "flow_released") == "birth_capture"
        and states.get("author_release", {}).get("on", {}).get("flow_released", [{}])[0].get("guard")
        == "released_candidate_is_unpublished"
        and _target(states, "author_release", "flow_released", 1) == "blocked"
        and _target(states, "author_release", "publication_boundary_violated") == "blocked",
        "release must stop unpublished for birth capture and block any early publication",
    )
    check(
        states.get("private_publish", {}).get("on", {}).get("play_published", [{}])[0].get("guard")
        == "private_publication_matches_captured_birth"
        and states.get("public_publish", {}).get("on", {}).get("play_published", [{}])[0].get("guard")
        == "public_publication_matches_captured_birth"
        and _target(states, "private_publish", "play_published", 1) == "blocked"
        and _target(states, "public_publish", "play_published", 1) == "blocked",
        "publication receipts must match the captured birth before binding",
    )
    check(
        edges["use_receipt"]
        == {"onboarding_activation_present", "receipt", "blocked"},
        "Use receipt may explain first activation but must not publish or index",
    )
    check(_target(states, "save_offer", "save_skipped") == "completed", "Skip must complete without publication or indexing")
    for field in (
        "mode",
        "resolution",
        "modality_policy",
        "judge_policy",
        "output_policy",
        "output",
        "onboarding",
        "exploration",
        "adapter_discovery",
        "handoff",
        "auth_repair",
        "publication_validation",
        "standby",
        "save_judge",
        "preferences",
        "last_event",
    ):
        check(field in context_roots, f"context schema must require {field}")
    modalities = context_schema.get("$defs", {}).get("modalityPolicy", {}).get("properties", {}).get("allowed", {}).get("items", {}).get("enum")
    check(modalities == ["call", "shell", "drive"], "CALL, SHELL, and DRIVE must be the closed modality set")
    execution_owner_enum = (
        context_schema.get("$defs", {})
        .get("execution", {})
        .get("properties", {})
        .get("owner", {})
        .get("enum")
    )
    handoff_owner_enum = (
        context_schema.get("$defs", {})
        .get("handoff", {})
        .get("properties", {})
        .get("owner", {})
        .get("enum")
    )
    expected_owner_enum = [*expected_specialists, None]
    check(
        execution_owner_enum == expected_owner_enum,
        "execution.owner must reject direct MCP and non-Rote executors",
    )
    check(
        handoff_owner_enum == expected_owner_enum,
        "handoff.owner must use the same closed Rote specialist set",
    )
    candidate_schema = context_schema.get("$defs", {}).get("candidate", {})
    check(
        "publication_status" in candidate_schema.get("required", [])
        and candidate_schema.get("properties", {})
        .get("publication_status", {})
        .get("enum")
        == ["unknown", "unpublished", "published"],
        "candidate context must track the pre-publication lifecycle boundary",
    )
    publication_schema = context_schema.get("$defs", {}).get("publication", {})
    owner_fields = {
        "owner_resolution",
        "profile_handle",
        "owner_choices",
        "owner_summary",
        "owner_probe_ref",
        "owner_probe_ns",
    }
    check(
        owner_fields <= set(publication_schema.get("required", []))
        and publication_schema.get("properties", {})
        .get("owner_resolution", {})
        .get("enum")
        == ["unknown", "resolved", "choice_required", "unavailable"],
        "publication context must retain typed pre-save owner resolution",
    )
    auth_repair_owner_enum = (
        context_schema.get("$defs", {})
        .get("authRepair", {})
        .get("properties", {})
        .get("owner", {})
        .get("enum")
    )
    check(
        auth_repair_owner_enum == ["rote-adapter-config", None],
        "auth repair must use a separate closed rote-adapter-config owner",
    )
    check(
        actions.get("prepare_auth_repair_handoff", {}).get("command")
        == "scripts/bin/play-handoff prepare-auth-repair --stdin --json",
        "auth repair availability must use its dedicated handoff gate",
    )
    check(
        actions.get("validate_auth_repair_receipt", {}).get("command")
        == "scripts/bin/play-handoff verify-auth-repair --stdin --json",
        "auth repair receipts must use their dedicated verification gate",
    )
    check(
        actions.get("present_birth_certificate", {}).get("command")
        == "scripts/bin/play-certificate --stdin --json",
        "saved Play completion must use the typed birth certificate renderer",
    )
    check(
        actions.get("inspect_publication_credentials", {}).get("command")
        == "scripts/bin/play-publication-gate credentials --stdin --json",
        "public publication credentials must use the deterministic metadata-only gate",
    )
    check(
        actions.get("smoke_publication", {}).get("command")
        == "scripts/bin/play-publication-gate smoke --stdin --json",
        "public publication smoke must use the isolated canonical-run gate",
    )
    public_fields = actions.get("publish_public", {}).get("events", {}).get("play_published", [])
    check(
        "publication.uri" in public_fields and "publication.install_uri" in public_fields,
        "public publication must preserve registry-returned Play and install URIs",
    )
    owner_action = actions.get("resolve_public_owner", {})
    owner_policy = " ".join(owner_action.get("command_policy", []))
    check(
        owner_action.get("owner") == "play"
        and owner_action.get("effect") == "read"
        and "rote registry whoami --verbose" in owner_policy
        and "rote registry org list --json" in owner_policy
        and "never run or recommend rote profile set-handle" in owner_policy,
        "public owner resolution must probe claimed handles and authorized orgs without mutation",
    )
    save_prompt = prompts.get("private_public_or_skip", {})
    owner_prompt = prompts.get("select_public_owner", {})
    owner_source = owner_prompt.get("choices_from", {})
    check(
        save_prompt.get("template_fields") == ["publication.owner_summary"]
        and owner_prompt.get("template_fields") == ["publication.owner_summary"]
        and owner_source.get("context") == "publication.owner_choices"
        and owner_source.get("value_source_field") == "owner"
        and owner_source.get("value_field") == "publication.owner",
        "save and owner prompts must render the typed preflight namespace choices",
    )
    release_action = actions.get("author_release", {})
    private_publish_action = actions.get("publish_private", {})
    public_publish_action = actions.get("publish_public", {})
    check(
        release_action.get("specialist") == "rote-flow-authoring"
        and private_publish_action.get("specialist") == "rote-registry"
        and public_publish_action.get("specialist") == "rote-registry",
        "release and publication must use separate closed specialists",
    )
    release_policy = " ".join(release_action.get("command_policy", []))
    check(
        "stop before every registry push" in release_policy
        and "Never delegate an end-to-end release-and-publish request" in release_policy
        and "publication_boundary_violated" in release_action.get("events", {}),
        "author release must return before publication and report boundary violations",
    )
    for action_name, action in (
        ("publish_private", private_publish_action),
        ("publish_public", public_publish_action),
    ):
        policy = " ".join(action.get("command_policy", []))
        check(
            "birth.sha256" in action.get("input_required", [])
            and "birth.capture_ref" in action.get("input_required", [])
            and "birth.sha256" in action.get("events", {}).get("play_published", [])
            and "publication.birth_sha256"
            in action.get("events", {}).get("play_published", [])
            and "publication-only handoff" in policy,
            f"{action_name} must be a post-capture publication-only handoff",
        )
    presentation_policy = " ".join(
        actions.get("present_birth_certificate", {}).get("command_policy", [])
    )
    check(
        "ready to paste into X and LinkedIn" in presentation_policy
        and "Never invent, reconstruct, shorten, or silently omit" in presentation_policy
        and "same redacted trace" in presentation_policy
        and "we did an excellent job" in presentation_policy,
        "the certificate must include truthful trace learning, social copy, and personalized closure",
    )
    credential_policy = " ".join(
        actions.get("inspect_publication_credentials", {}).get("command_policy", [])
    )
    smoke_policy = " ".join(actions.get("smoke_publication", {}).get("command_policy", []))
    check(
        "Never inspect, print, hash, copy, or persist a credential value" in credential_policy
        and "equal fingerprints as insufficient" in credential_policy,
        "public credential validation must compare contracts without reading secrets",
    )
    check(
        "exactly one rote play run" in smoke_policy
        and "fresh temporary working directory under /tmp" in smoke_policy,
        "public smoke must run the exact canonical URI from isolated local context",
    )
    judge_policy_text = " ".join(
        actions.get("judge_save_worthiness", {}).get("command_policy", [])
    )
    check(
        "trace evidence, not conversation prose" in judge_policy_text
        and "capture handle" in judge_policy_text
        and "failed or abandoned task" in judge_policy_text,
        "save worthiness must require captured trace evidence and a failure gate",
    )
    standby_policy_text = " ".join(
        actions.get("record_standby", {}).get("command_policy", [])
    )
    check(
        "capture/normal decision" in standby_policy_text
        and "explicit statement" in standby_policy_text,
        "standby must apply capture policy and ledger only explicit statements",
    )
    check(
        "One reading per captured rote call" in standby_policy_text
        and "crystallizes into a monolith" in standby_policy_text,
        "the baton-pass must carry exploration-shape steering",
    )
    crystallize_policy_text = " ".join(
        actions.get("prepare_candidate", {}).get("command_policy", [])
    )
    check(
        "One reading = one step" in crystallize_policy_text
        and "labeled unknown" in crystallize_policy_text
        and "--yes equivalent" in crystallize_policy_text,
        "crystallization must carry play-shape steering",
    )
    release_shape_text = " ".join(
        actions.get("author_release", {}).get("command_policy", [])
    )
    check(
        "Test the negative space before release" in release_shape_text
        and "stage ledger" in release_shape_text,
        "release must gate on shape standards and negative-space testing",
    )
    outcome_fields = (
        handoff_schema.get("$defs", {})
        .get("packet", {})
        .get("properties", {})
        .get("expected_events", {})
        .get("properties", {})
        .get("outcome_ready", {})
        .get("const", [])
    )
    check(
        "route_provenance" in outcome_fields,
        "handoff receipts must require route provenance",
    )
    packet_schema = handoff_schema.get("$defs", {}).get("packet", {})
    check(
        "adapter_discovery" in packet_schema.get("required", []),
        "CALL handoff packets must bind typed adapter discovery evidence",
    )
    discovery_order = (
        packet_schema.get("properties", {})
        .get("capability_policy", {})
        .get("oneOf", [{}])[0]
        .get("properties", {})
        .get("discovery_order", {})
        .get("const")
    )
    check(
        discovery_order == ["installed", "catalog", "provided_spec", "provider_docs"],
        "CALL handoff discovery must search installed adapters then catalog before specs",
    )
    auth_required_fields = (
        handoff_schema.get("$defs", {})
        .get("packet", {})
        .get("properties", {})
        .get("expected_events", {})
        .get("properties", {})
        .get("auth_repair_required", {})
        .get("const", [])
    )
    check(
        auth_required_fields == ["auth_repair"],
        "CALL handoff receipts must expose the typed auth repair event",
    )
    check(
        handoff_schema.get("$defs", {})
        .get("authRepairPacket", {})
        .get("properties", {})
        .get("owner", {})
        .get("const")
        == "rote-adapter-config",
        "auth repair packets must be closed to rote-adapter-config",
    )

    if errors:
        raise MachineValidationError(errors)
    transitions = sum(
        len(branches)
        for state in states.values()
        for branches in state.get("on", {}).values()
    )
    return ValidationSummary(len(states), transitions, len(actions), len(prompts))
