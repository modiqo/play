"""Typed execution kernel for the declarative Play controller."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, NewType

from statemachine.io import create_machine_class_from_definition

from .machine import MachineValidationError, validate_bundle


StateId = NewType("StateId", str)
EventId = NewType("EventId", str)
GuardId = NewType("GuardId", str)
MutationId = NewType("MutationId", str)


class ControllerRuntimeError(RuntimeError):
    """The controller bundle or a requested transition is invalid."""


@dataclass(frozen=True)
class TransitionSpec:
    target: StateId
    mutation: MutationId
    guard: GuardId | None = None


@dataclass(frozen=True)
class StateSpec:
    id: StateId
    terminal: bool
    events: Mapping[EventId, tuple[TransitionSpec, ...]]


@dataclass(frozen=True)
class ControllerEvent:
    id: EventId
    payload: Mapping[str, Any]
    guards: Mapping[GuardId, bool]


@dataclass(frozen=True)
class LastEvent:
    id: EventId
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ControllerCursor:
    schema: str
    bundle_sha256: str
    run_id: str
    task_key: str
    state: StateId
    transition_seq: int
    last_event: LastEvent | None


@dataclass(frozen=True)
class TransitionRecord:
    source: StateId
    target: StateId
    event: EventId
    guard: GuardId | None
    mutation: MutationId


@dataclass(frozen=True)
class RuntimeTiming:
    compile_ns: int
    step_ns: int


@dataclass(frozen=True)
class StepResult:
    cursor: ControllerCursor
    transition: TransitionRecord
    timing: RuntimeTiming

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeModel:
    """Typed domain model used by python-statemachine to store current state."""

    state: str


@dataclass(frozen=True)
class ControllerBundle:
    schema: str
    initial: StateId
    terminals: frozenset[StateId]
    guards: frozenset[GuardId]
    states: Mapping[StateId, StateSpec]
    event_requirements: Mapping[tuple[StateId, EventId], tuple[str, ...]]
    sha256: str

    @classmethod
    def load(cls, root: Path) -> ControllerBundle:
        try:
            validate_bundle(root)
        except MachineValidationError as error:
            raise ControllerRuntimeError("; ".join(error.errors)) from error

        controller = root / "references" / "controller"
        documents = {
            "machine": _load_yaml(controller / "machine.yaml"),
            "actions": _load_yaml(controller / "actions.yaml"),
            "prompts": _load_yaml(controller / "prompts.yaml"),
        }
        machine = documents["machine"]
        actions_document = documents["actions"]
        prompts_document = documents["prompts"]
        terminals = frozenset(StateId(value) for value in machine["terminal"])
        states: dict[StateId, StateSpec] = {}
        guards: set[GuardId] = set()
        requirements: dict[tuple[StateId, EventId], tuple[str, ...]] = {}

        for state_name, raw_state in machine["states"].items():
            state_id = StateId(state_name)
            events: dict[EventId, tuple[TransitionSpec, ...]] = {}
            for event_name, raw_branches in raw_state.get("on", {}).items():
                event_id = EventId(event_name)
                events[event_id] = tuple(
                    TransitionSpec(
                        target=StateId(branch["target"]),
                        mutation=MutationId(branch["mutate"]),
                        guard=GuardId(branch["guard"]) if branch.get("guard") else None,
                    )
                    for branch in raw_branches
                )
                guards.update(
                    branch.guard for branch in events[event_id] if branch.guard is not None
                )
            states[state_id] = StateSpec(
                id=state_id,
                terminal=state_id in terminals,
                events=events,
            )
            requirements.update(
                _event_requirements(
                    state_id,
                    raw_state,
                    actions_document,
                    prompts_document,
                )
            )

        canonical = json.dumps(documents, sort_keys=True, separators=(",", ":"))
        return cls(
            schema=machine["schema"],
            initial=StateId(machine["initial"]),
            terminals=terminals,
            guards=frozenset(guards),
            states=states,
            event_requirements=requirements,
            sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        )


class ControllerRuntime:
    """Compile Play's YAML once and execute typed, fail-closed transitions."""

    def __init__(self, root: Path):
        started = time.perf_counter_ns()
        self.bundle = ControllerBundle.load(root)
        self._chart_class = _compile_chart(self.bundle)
        self.compile_ns = time.perf_counter_ns() - started

    def initial_cursor(self, *, run_id: str, task_key: str) -> ControllerCursor:
        if not run_id or not task_key:
            raise ControllerRuntimeError("run_id and task_key must be non-empty")
        return ControllerCursor(
            schema="play.runtime-cursor/v1",
            bundle_sha256=self.bundle.sha256,
            run_id=run_id,
            task_key=task_key,
            state=self.bundle.initial,
            transition_seq=0,
            last_event=None,
        )

    def step(self, cursor: ControllerCursor, event: ControllerEvent) -> StepResult:
        started = time.perf_counter_ns()
        self._validate_cursor(cursor)
        state = self.bundle.states[cursor.state]
        if state.terminal:
            raise ControllerRuntimeError(f"terminal state {cursor.state!r} accepts no events")
        branches = state.events.get(event.id)
        if branches is None:
            raise ControllerRuntimeError(
                f"state {cursor.state!r} does not accept event {event.id!r}"
            )
        _validate_event_payload(
            event.payload,
            self.bundle.event_requirements.get((cursor.state, event.id), ()),
        )
        selected = _select_transition(branches, event.guards)

        listener = _guard_listener(self.bundle.guards, event.guards)
        model = RuntimeModel(state=str(cursor.state))
        chart = self._chart_class(model=model, listeners=[listener])
        chart.send(str(event.id))
        actual_target = StateId(model.state)
        if actual_target != selected.target:
            raise ControllerRuntimeError(
                "compiled statechart disagreed with the Play transition contract: "
                f"expected {selected.target!r}, got {actual_target!r}"
            )

        next_cursor = ControllerCursor(
            schema=cursor.schema,
            bundle_sha256=cursor.bundle_sha256,
            run_id=cursor.run_id,
            task_key=cursor.task_key,
            state=selected.target,
            transition_seq=cursor.transition_seq + 1,
            last_event=LastEvent(event.id, dict(event.payload)),
        )
        timing = RuntimeTiming(
            compile_ns=self.compile_ns,
            step_ns=time.perf_counter_ns() - started,
        )
        return StepResult(
            cursor=next_cursor,
            transition=TransitionRecord(
                source=cursor.state,
                target=selected.target,
                event=event.id,
                guard=selected.guard,
                mutation=selected.mutation,
            ),
            timing=timing,
        )

    def _validate_cursor(self, cursor: ControllerCursor) -> None:
        if cursor.schema != "play.runtime-cursor/v1":
            raise ControllerRuntimeError(f"unsupported cursor schema {cursor.schema!r}")
        if cursor.bundle_sha256 != self.bundle.sha256:
            raise ControllerRuntimeError("cursor belongs to a different controller bundle")
        if cursor.state not in self.bundle.states:
            raise ControllerRuntimeError(f"unknown cursor state {cursor.state!r}")
        if cursor.transition_seq < 0:
            raise ControllerRuntimeError("transition_seq cannot be negative")


def cursor_from_dict(payload: Mapping[str, Any]) -> ControllerCursor:
    last = payload.get("last_event")
    last_event = None
    if last is not None:
        if not isinstance(last, Mapping):
            raise ControllerRuntimeError("last_event must be an object or null")
        last_event = LastEvent(
            id=EventId(_required_string(last, "id")),
            payload=_required_mapping(last, "payload"),
        )
    sequence = payload.get("transition_seq")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise ControllerRuntimeError("transition_seq must be an integer")
    return ControllerCursor(
        schema=_required_string(payload, "schema"),
        bundle_sha256=_required_string(payload, "bundle_sha256"),
        run_id=_required_string(payload, "run_id"),
        task_key=_required_string(payload, "task_key"),
        state=StateId(_required_string(payload, "state")),
        transition_seq=sequence,
        last_event=last_event,
    )


def event_from_dict(payload: Mapping[str, Any]) -> ControllerEvent:
    raw_guards = payload.get("guards", {})
    if not isinstance(raw_guards, Mapping) or any(
        not isinstance(name, str) or not isinstance(value, bool)
        for name, value in raw_guards.items()
    ):
        raise ControllerRuntimeError("guards must be a string-to-boolean object")
    return ControllerEvent(
        id=EventId(_required_string(payload, "id")),
        payload=_required_mapping(payload, "payload"),
        guards={GuardId(name): value for name, value in raw_guards.items()},
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        payload = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ControllerRuntimeError(f"cannot load {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ControllerRuntimeError(f"{path} must contain an object")
    return payload


def _event_requirements(
    state: StateId,
    raw_state: Mapping[str, Any],
    actions_document: Mapping[str, Any],
    prompts_document: Mapping[str, Any],
) -> dict[tuple[StateId, EventId], tuple[str, ...]]:
    if action_ref := raw_state.get("entry"):
        action = actions_document["actions"][action_ref["action"]]
        declared = action.get("events_by_state", {}).get(str(state)) or action.get("events", {})
        failure = actions_document.get("failure_event", {})
        declared = {**declared, failure.get("id"): failure.get("required", [])}
    elif prompt_id := raw_state.get("prompt"):
        declared = prompts_document["prompts"][prompt_id]["events"]
    else:
        declared = {}
    return {
        (state, EventId(name)): tuple(fields)
        for name, fields in declared.items()
        if isinstance(name, str)
    }


def _compile_chart(bundle: ControllerBundle) -> type[Any]:
    definition: dict[str, Any] = {"states": {}}
    states = definition["states"]
    for state_id, state in bundle.states.items():
        raw: dict[str, Any] = {
            "initial": state_id == bundle.initial,
            "final": state.terminal,
        }
        if state.events:
            raw["on"] = {
                str(event): [
                    {
                        "target": str(branch.target),
                        **({"cond": str(branch.guard)} if branch.guard else {}),
                    }
                    for branch in branches
                ]
                for event, branches in state.events.items()
            }
        states[str(state_id)] = raw
    chart_class = create_machine_class_from_definition("PlayControllerChart", **definition)
    chart_class.allow_event_without_transition = False
    chart_class.catch_errors_as_events = False
    return chart_class


def _guard_listener(
    declared: frozenset[GuardId], values: Mapping[GuardId, bool]
) -> object:
    callbacks: dict[str, Any] = {}
    for guard in declared:
        callbacks[str(guard)] = _constant_guard(values.get(guard, False))
    return type("PlayGuardListener", (), callbacks)()


def _constant_guard(value: bool) -> Any:
    def evaluate(_self: object, **_kwargs: Any) -> bool:
        return value

    return evaluate


def _select_transition(
    branches: tuple[TransitionSpec, ...],
    guards: Mapping[GuardId, bool],
) -> TransitionSpec:
    for branch in branches:
        if branch.guard is None or guards.get(branch.guard, False):
            return branch
    raise ControllerRuntimeError("no transition guard was satisfied")


def _validate_event_payload(payload: Mapping[str, Any], required: tuple[str, ...]) -> None:
    missing = [path for path in required if not _has_path(payload, path)]
    if missing:
        raise ControllerRuntimeError(
            "event payload is missing required fields: " + ", ".join(missing)
        )


def _has_path(payload: Mapping[str, Any], path: str) -> bool:
    if path in payload:
        return True
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ControllerRuntimeError(f"{field} must be a non-empty string")
    return value


def _required_mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise ControllerRuntimeError(f"{field} must be an object")
    return value
