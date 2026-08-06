"""Validation for the declarative Play controller bundle."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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


def validate_bundle(root: Path) -> ValidationSummary:
    controller = root / "references" / "controller"
    machine = _load_yaml(controller / "machine.yaml")
    actions_doc = _load_yaml(controller / "actions.yaml")
    prompts_doc = _load_yaml(controller / "prompts.yaml")
    machine_schema = _load_json(controller / "machine.schema.json")
    context_schema = _load_json(controller / "context.schema.json")
    handoff_schema = _load_json(controller / "handoff.schema.json")
    errors: list[str] = []

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
    initial = machine.get("initial")
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
    check(initial in states, f"initial state {initial!r} is missing")
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

    for name, prompt in prompts.items():
        question = prompt.get("question")
        check(isinstance(question, str) and question.strip().endswith("?"),
              f"prompt {name}: question must be a non-empty question ending in ?")
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
            for field in ("context", "label_field", "description_field", "value_field", "event"):
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
        for required in action.get("input_required", []):
            root_name = required.split(".", 1)[0]
            check(root_name in context_roots,
                  f"action {name}: input root {root_name!r} is absent from durable context")

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
        "explore_handoff": ("explore_execute", "explore_receipt", "explore_verify"),
        "explore_execute": ("explore_receipt", "explore_verify"),
        "explore_receipt": ("explore_verify",),
        "crystallize": ("save_offer", "author_release", "birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect"),
        "save_offer": ("author_release", "birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect"),
        "author_release": ("birth_capture", "private_publish", "public_publish", "birth_bind", "index", "saved_inspect"),
        "birth_capture": ("private_publish", "public_publish", "birth_bind", "index", "saved_inspect"),
        "birth_bind": ("index", "saved_inspect"),
        "index": ("saved_inspect",),
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
    check(states.get("use_offer", {}).get("prompt") == "approve_play_run", "Use must ask for post-inspection execution approval")
    check(states.get("use_run", {}).get("entry", {}).get("action") == "run_registry_play", "Use mode must be owned by run_registry_play")
    check(actions.get("inspect_registry_play", {}).get("command") == "scripts/bin/play-inspect <match.reference> --json", "Use inspection must invoke the reusable first-class wrapper")
    check(actions.get("run_registry_play", {}).get("command") == "rote play run <inspection.exact_reference> <approved-parameters> --yes", "Use mode must invoke the approved exact Play")
    check(actions.get("inspect_saved_play", {}).get("command") == "rote play inspect <publication.canonical_reference> --json", "saved Play readback must invoke rote play inspect --json")
    check(actions.get("search_authorized_plays", {}).get("command") == "scripts/bin/play-search <request.intent> --json", "Play discovery must invoke the unified local and registry search")
    check(_target(states, "qualify", "play_awareness_request") == "awareness_collect", "an awareness request must enter the digest path")
    check(actions.get("collect_awareness_digest", {}).get("effect") == "local-write", "awareness collection may write only remembered local state")
    check(actions.get("collect_awareness_digest", {}).get("command") == "scripts/bin/play-digest --remember --days <awareness.window_days> --json", "awareness must invoke the remembered digest command")
    check(_target(states, "awareness_collect", "awareness_unchanged") == "completed", "unchanged awareness must finish without an action prompt")
    check(_target(states, "awareness_offer", "awareness_play_selected") == "use_inspect", "an exact awareness selection must enter inspection")
    check(_target(states, "qualify", "play_creation_request") == "creator_search", "explicit creator intent must search before exploration")
    check(_target(states, "creator_classify", "creator_no_match") == "explore_prepare", "creator intent without a match must skip the redundant Explore prompt")
    check(
        _target(states, "explore_route", "route_selected") == "explore_handoff",
        "an approved route must prove specialist availability before execution",
    )
    check(
        _target(states, "explore_handoff", "specialist_handoff_ready") == "explore_execute",
        "only a prepared specialist handoff may enter Explore execution",
    )
    check(
        _target(states, "explore_handoff", "specialist_unavailable") == "blocked",
        "an unavailable specialist must block without direct-tool fallback",
    )
    check(
        _target(states, "explore_execute", "outcome_ready") == "explore_receipt",
        "delegated output must enter receipt validation before verification",
    )
    check(
        _target(states, "explore_receipt", "specialist_outcome_ready") == "explore_verify",
        "only a validated specialist receipt may enter outcome verification",
    )
    check(
        _target(states, "explore_receipt", "specialist_receipt_invalid") == "blocked",
        "an invalid specialist receipt must block",
    )
    for forbidden in ("use_preflight", "use_resolve"):
        check(forbidden not in states, f"{forbidden} must stay inside the rote play run controller")
    check(predecessors["use_run"] == {"use_offer"}, "execution may follow only post-inspection approval")
    check("use_inspect" in dominators["use_run"], "inspection must dominate execution")
    check(
        predecessors["explore_execute"] == {"explore_handoff"},
        "Explore execution may follow only a prepared specialist handoff",
    )
    check(
        predecessors["explore_receipt"] == {"explore_execute"},
        "specialist receipt validation may follow only delegated execution",
    )
    check(
        predecessors["explore_verify"] == {"explore_receipt"},
        "Explore verification may follow only a validated specialist receipt",
    )
    check(predecessors["birth_bind"] == {"private_publish", "public_publish"}, "birth binding may follow only successful private or public publication")
    check(predecessors["index"] == {"birth_bind"}, "index may follow only successful birth binding")
    check(predecessors["saved_inspect"] == {"index"}, "saved inspection may follow only successful indexing")
    check(edges["use_receipt"] == {"receipt", "blocked"}, "Use receipt must terminate without publication or indexing")
    check(_target(states, "save_offer", "save_skipped") == "completed", "Skip must complete without publication or indexing")
    for field in ("mode", "resolution", "modality_policy", "judge_policy", "handoff", "last_event"):
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
    check(
        actions.get("prepare_specialist_handoff", {}).get("command")
        == "scripts/bin/play-handoff prepare --stdin --json",
        "specialist availability must use the reusable handoff gate",
    )
    check(
        actions.get("validate_specialist_receipt", {}).get("command")
        == "scripts/bin/play-handoff verify --stdin --json",
        "specialist receipts must use the reusable verification gate",
    )
    execute_policy = " ".join(actions.get("execute_route", {}).get("command_policy", []))
    check(
        "must not call MCP, app, shell, or browser tools directly" in execute_policy,
        "delegated Explore must explicitly forbid direct tool execution",
    )
    check(
        "determine OpenAPI, GraphQL, or MCP" in execute_policy,
        "CALL adapter creation must auto-detect its substrate",
    )
    check(
        "Rote-owned authentication cycle" in execute_policy,
        "CALL adapter execution must complete authentication through Rote",
    )
    check(
        "route_provenance"
        in actions.get("execute_route", {}).get("events", {}).get("outcome_ready", []),
        "successful delegated execution must report route provenance",
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

    if errors:
        raise MachineValidationError(errors)
    transitions = sum(
        len(branches)
        for state in states.values()
        for branches in state.get("on", {}).values()
    )
    return ValidationSummary(len(states), transitions, len(actions), len(prompts))
