"""Typed execution kernel for the declarative Play controller."""

from __future__ import annotations

import hashlib
import json
import time
import base64
import copy
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, NewType

from jsonschema import Draft202012Validator
from statemachine.io import create_machine_class_from_definition

from .machine import MachineValidationError, validate_bundle
from .elicitation import native_payload, parse_question
from .executors import action_executor
from .runtime_context import (
    RuntimeContextError,
    apply_event,
    initial_context,
    validate_context,
    validate_mutation_contract,
    validate_required,
)


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
    owner: str
    checkpoint: str | None
    requires: tuple[str, ...]
    action: str | None
    prompt: str | None
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


@dataclass(frozen=True)
class StateProjection:
    schema: str
    bundle_sha256: str
    state: Mapping[str, Any]
    instruction: Mapping[str, Any] | None
    accepted_events: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdvanceResult:
    schema: str
    step: StepResult
    projection: StateProjection

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "step": self.step.as_dict(),
            "projection": self.projection.as_dict(),
        }


@dataclass(frozen=True)
class RuntimeSession:
    schema: str
    cursor: ControllerCursor
    context: Mapping[str, Any]
    preflight_ready: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionAdvanceResult:
    schema: str
    session: RuntimeSession
    step: StepResult
    projection: StateProjection

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "session": self.session.as_dict(),
            "step": self.step.as_dict(),
            "projection": self.projection.as_dict(),
        }


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
    actions: Mapping[str, Mapping[str, Any]]
    prompts: Mapping[str, Mapping[str, Any]]
    context_schema: Mapping[str, Any]
    event_requirements: Mapping[tuple[StateId, EventId], tuple[str, ...]]
    sha256: str

    @classmethod
    def load(cls, root: Path) -> ControllerBundle:
        controller = root / "references" / "controller"
        documents = {
            "machine": _load_yaml(controller / "machine.yaml"),
            "actions": _load_yaml(controller / "actions.yaml"),
            "prompts": _load_yaml(controller / "prompts.yaml"),
            "machine_schema": _load_json(controller / "machine.schema.json"),
            "context_schema": _load_json(controller / "context.schema.json"),
            "handoff_schema": _load_json(controller / "handoff.schema.json"),
        }
        try:
            validate_bundle(root, documents=documents)
        except MachineValidationError as error:
            raise ControllerRuntimeError("; ".join(error.errors)) from error

        machine = documents["machine"]
        actions_document = documents["actions"]
        prompts_document = documents["prompts"]
        try:
            validate_mutation_contract(actions_document["mutations"])
        except RuntimeContextError as error:
            raise ControllerRuntimeError(str(error)) from error
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
                owner=str(raw_state.get("owner", "")),
                checkpoint=raw_state.get("checkpoint"),
                requires=tuple(raw_state.get("requires", ())),
                action=(raw_state.get("entry") or {}).get("action"),
                prompt=raw_state.get("prompt"),
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
            actions=actions_document["actions"],
            prompts=prompts_document["prompts"],
            context_schema=documents["context_schema"],
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

    def initial_session(
        self, *, run_id: str, task_key: str, request_original: str
    ) -> RuntimeSession:
        cursor = self.initial_cursor(run_id=run_id, task_key=task_key)
        context = initial_context(
            run_id=run_id,
            task_key=task_key,
            machine_version=self.bundle.sha256,
            request_original=request_original,
        )
        try:
            validate_context(context, self.bundle.context_schema)
            validate_required(context, self.bundle.states[cursor.state].requires)
        except RuntimeContextError as error:
            raise ControllerRuntimeError(str(error)) from error
        return RuntimeSession(
            schema="play.runtime-session/v1",
            cursor=cursor,
            context=context,
            preflight_ready=False,
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
            self.bundle.context_schema,
        )
        guard_values = _resolve_guard_values(event)
        selected = _select_transition(branches, guard_values)

        listener = _guard_listener(self.bundle.guards, guard_values)
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

    def project(
        self,
        cursor: ControllerCursor,
        context: Mapping[str, Any] | None = None,
    ) -> StateProjection:
        """Return only the executable contract for the cursor's current state."""

        self._validate_cursor(cursor)
        state = self.bundle.states[cursor.state]
        instruction: dict[str, Any] | None
        if state.terminal:
            boundary = "terminal"
            instruction = None
        elif state.action is not None:
            action = self.bundle.actions[state.action]
            kind = str(action["kind"])
            executor = action_executor(state.action, action)
            if executor is None:
                raise ControllerRuntimeError(
                    f"action {state.action} has no closed executor contract"
                )
            boundary = executor
            specialist = action.get("specialist")
            specialist_from = action.get("specialist_from")
            if specialist_from is not None:
                if context is None or not isinstance(specialist_from, str):
                    raise ControllerRuntimeError(
                        f"action {state.action} cannot resolve its specialist"
                    )
                specialist = _path_value(context, specialist_from)
            if kind == "delegated" and not isinstance(specialist, str):
                raise ControllerRuntimeError(
                    f"delegated action {state.action} lacks an exact specialist"
                )
            instruction = {
                "type": "action",
                "id": state.action,
                "kind": kind,
                "executor": executor,
                "owner": action["owner"],
                "effect": action["effect"],
                **({"specialist": specialist} if isinstance(specialist, str) else {}),
                "input_required": list(action.get("input_required", ())),
                **({"command": action["command"]} if action.get("command") else {}),
                **(
                    {"timeout_seconds": action["timeout_seconds"]}
                    if action.get("timeout_seconds") is not None
                    else {}
                ),
                **(
                    {"command_policy": list(action["command_policy"])}
                    if action.get("command_policy")
                    else {}
                ),
                **(
                    {"input": _select_context(context, action.get("input_required", ())) }
                    if context is not None
                    else {}
                ),
            }
        elif state.prompt is not None:
            prompt = self.bundle.prompts[state.prompt]
            boundary = "human"
            question = parse_question(state.prompt, dict(prompt))
            rendered = native_payload(question, "generic", context or {})
            instruction = {
                "type": "prompt",
                "id": state.prompt,
                "question": rendered["question"],
                "selection": rendered["selection"],
                "minimum_selected": rendered["minimum_selected"],
                "choices": rendered["choices"],
                "input": rendered["input"],
                "events": dict(prompt.get("events", {})),
            }
        else:
            raise ControllerRuntimeError(
                f"non-terminal state {cursor.state!r} has no instruction"
            )

        accepted_events = {}
        for event, branches in state.events.items():
            required_payload = self.bundle.event_requirements.get((state.id, event), ())
            accepted_events[str(event)] = {
                "required_payload": list(required_payload),
                "payload_schema": _event_payload_schema(
                    required_payload, self.bundle.context_schema
                ),
                "guards": [str(branch.guard) for branch in branches if branch.guard],
                "event_template": {
                    "id": str(event),
                    "payload": _event_payload_template(required_payload, context),
                    "guards": {},
                },
            }
        return StateProjection(
            schema="play.runtime-projection/v1",
            bundle_sha256=self.bundle.sha256,
            state={
                "id": str(state.id),
                "terminal": state.terminal,
                "owner": state.owner,
                "checkpoint": state.checkpoint,
                "requires": list(state.requires),
                "boundary": boundary,
            },
            instruction=instruction,
            accepted_events=accepted_events,
        )

    def advance(
        self, cursor: ControllerCursor, event: ControllerEvent
    ) -> AdvanceResult:
        step = self.step(cursor, event)
        return AdvanceResult(
            schema="play.runtime-advance/v1",
            step=step,
            projection=self.project(step.cursor),
        )

    def project_session(self, session: RuntimeSession) -> StateProjection:
        self._validate_session(session)
        return self.project(session.cursor, session.context)

    def advance_session(
        self, session: RuntimeSession, event: ControllerEvent
    ) -> SessionAdvanceResult:
        self._validate_session(session)
        event = _canonicalize_specialist_event(session, event)
        _validate_inspected_parameter_event(session, event)
        event = _derive_session_guards(session, event)
        step = self.step(session.cursor, event)
        try:
            context = apply_event(
                session.context,
                event_id=str(event.id),
                payload=event.payload,
                state=str(step.cursor.state),
                transition_seq=step.cursor.transition_seq,
                mutation=str(step.transition.mutation),
            )
            validate_required(context, self.bundle.states[step.cursor.state].requires)
            validate_context(context, self.bundle.context_schema)
        except RuntimeContextError as error:
            raise ControllerRuntimeError(str(error)) from error
        next_session = RuntimeSession(
            schema=session.schema,
            cursor=step.cursor,
            context=context,
            preflight_ready=session.preflight_ready,
        )
        return SessionAdvanceResult(
            schema="play.runtime-session-advance/v1",
            session=next_session,
            step=step,
            projection=self.project_session(next_session),
        )

    def _validate_session(self, session: RuntimeSession) -> None:
        if session.schema != "play.runtime-session/v1":
            raise ControllerRuntimeError(f"unsupported session schema {session.schema!r}")
        self._validate_cursor(session.cursor)
        if session.context.get("machine_version") != self.bundle.sha256:
            raise ControllerRuntimeError("session context belongs to a different controller bundle")
        if session.context.get("run_id") != session.cursor.run_id:
            raise ControllerRuntimeError("session context run_id differs from cursor")
        if session.context.get("task_key") != session.cursor.task_key:
            raise ControllerRuntimeError("session context task_key differs from cursor")
        if session.context.get("state") != session.cursor.state:
            raise ControllerRuntimeError("session context state differs from cursor")
        if session.context.get("transition_seq") != session.cursor.transition_seq:
            raise ControllerRuntimeError("session context transition_seq differs from cursor")

    def confirm_preflight(
        self, session: RuntimeSession, payload: Mapping[str, Any]
    ) -> RuntimeSession:
        self._validate_session(session)
        if payload.get("schema") != "play.preflight/v1" or payload.get("ready") is not True:
            raise ControllerRuntimeError("Play preflight is not ready")
        return RuntimeSession(
            schema=session.schema,
            cursor=session.cursor,
            context=session.context,
            preflight_ready=True,
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


def _canonicalize_specialist_event(
    session: RuntimeSession, event: ControllerEvent
) -> ControllerEvent:
    """Reduce legacy-Play authentication success to specialist-owned facts."""

    if (
        session.cursor.state != StateId("use_authentication_execute")
        or event.id != EventId("authentication_ready")
    ):
        return event
    raw = event.payload.get("authentication")
    if not isinstance(raw, Mapping):
        return event
    return ControllerEvent(
        id=event.id,
        payload={
            "authentication": {
                "authentication_action": raw.get("authentication_action"),
                "evidence_refs": raw.get("evidence_refs"),
            }
        },
        guards=event.guards,
    )


def _validate_inspected_parameter_event(
    session: RuntimeSession, event: ControllerEvent
) -> None:
    """Keep evaluator-produced execution parameters locked to frontmatter."""

    if session.cursor.state != StateId("use_decide") or event.id not in {
        EventId("play_parameter_required"),
        EventId("local_play_ready"),
        EventId("remote_pull_required"),
    }:
        return
    declarations = _path_value(session.context, "inspection.parameters")
    if not isinstance(declarations, list):
        raise ControllerRuntimeError("inspected parameter declarations are malformed")
    declared: dict[str, Mapping[str, Any]] = {}
    for declaration in declarations:
        if not isinstance(declaration, Mapping):
            raise ControllerRuntimeError("inspected parameter declaration is malformed")
        name = declaration.get("name")
        if not isinstance(name, str) or not name or name in declared:
            raise ControllerRuntimeError("inspected parameter names are invalid")
        declared[name] = declaration
    parameters = _path_value(event.payload, "request.parameters")
    if not isinstance(parameters, Mapping):
        raise ControllerRuntimeError("route_inspected_play parameters must be an object")
    unknown = sorted(set(parameters) - set(declared))
    if unknown:
        raise ControllerRuntimeError(
            "route_inspected_play returned undeclared parameter(s): "
            + ", ".join(unknown)
            + "; declared parameters: "
            + ", ".join(declared)
        )
    for name, value in parameters.items():
        declaration = declared[name]
        if not _matches_parameter_type(value, declaration.get("type")):
            raise ControllerRuntimeError(
                f"route_inspected_play returned the wrong type for parameter {name}"
            )
        valid_values = declaration.get("valid_values")
        if isinstance(valid_values, list) and valid_values and value not in valid_values:
            raise ControllerRuntimeError(
                f"route_inspected_play returned an invalid value for parameter {name}"
            )
    if event.id in {EventId("local_play_ready"), EventId("remote_pull_required")}:
        missing = [
            name
            for name, declaration in declared.items()
            if declaration.get("required") is True and name not in parameters
        ]
        if missing:
            raise ControllerRuntimeError(
                "route_inspected_play omitted required parameter(s): " + ", ".join(missing)
            )
    if event.id == EventId("play_parameter_required"):
        requested = _path_value(event.payload, "parameter_input.name")
        if requested not in declared:
            raise ControllerRuntimeError(
                "route_inspected_play requested an undeclared parameter"
            )


def _matches_parameter_type(value: Any, declared_type: Any) -> bool:
    normalized = str(declared_type or "string").casefold()
    if normalized in {"string", "str"}:
        return isinstance(value, str)
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"number", "float"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"array", "list"}:
        return isinstance(value, list)
    if normalized in {"object", "map"}:
        return isinstance(value, Mapping)
    return False


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


def session_from_dict(payload: Mapping[str, Any]) -> RuntimeSession:
    cursor = payload.get("cursor")
    context = payload.get("context")
    if not isinstance(cursor, Mapping) or not isinstance(context, Mapping):
        raise ControllerRuntimeError("session requires cursor and context objects")
    return RuntimeSession(
        schema=_required_string(payload, "schema"),
        cursor=cursor_from_dict(cursor),
        context=dict(context),
        preflight_ready=payload.get("preflight_ready") is True,
    )


def encode_session(session: RuntimeSession) -> str:
    raw = json.dumps(session.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    compressed = zlib.compress(raw, level=9)
    body = base64.urlsafe_b64encode(compressed).decode().rstrip("=")
    digest = hashlib.sha256(raw).hexdigest()
    return f"v1.{body}.{digest}"


def decode_session(token: str) -> RuntimeSession:
    try:
        version, body, expected_digest = token.split(".", 2)
        if version != "v1":
            raise ValueError("unsupported token version")
        padded = body + "=" * (-len(body) % 4)
        raw = zlib.decompress(base64.urlsafe_b64decode(padded))
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("digest mismatch")
        payload = json.loads(raw)
    except (ValueError, zlib.error, json.JSONDecodeError) as error:
        raise ControllerRuntimeError(f"invalid runtime session token: {error}") from error
    if not isinstance(payload, Mapping):
        raise ControllerRuntimeError("invalid runtime session token: payload is not an object")
    return session_from_dict(payload)


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        payload = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ControllerRuntimeError(f"cannot load {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ControllerRuntimeError(f"{path} must contain an object")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ControllerRuntimeError(f"cannot load {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ControllerRuntimeError(f"{path} must contain an object")
    return payload


def _select_context(
    context: Mapping[str, Any], paths: tuple[str, ...] | list[str]
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for path in paths:
        current: Any = context
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                break
            current = current[part]
        else:
            target = selected
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = current
    return selected


def _event_payload_template(
    required: tuple[str, ...], context: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Bind known event fields and expose null only for boundary-owned values."""

    payload: dict[str, Any] = {}
    for path in required:
        value = _path_value(context, path) if context is not None else None
        target = payload
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return payload


def _event_payload_schema(
    required: tuple[str, ...], context_schema: Mapping[str, Any]
) -> dict[str, Any]:
    """Project the exact, self-contained JSON Schema for one event payload."""

    tree: dict[str, Any] = {}
    for path in required:
        current = tree
        for part in path.split("."):
            current = current.setdefault(part, {})
        current["__declared__"] = True

    def render(node: Mapping[str, Any], prefix: tuple[str, ...]) -> dict[str, Any]:
        if node.get("__declared__") is True:
            schema = _materialize_schema_refs(
                _context_schema_at_path(context_schema, prefix), context_schema
            )
            if schema.get("type") == "object":
                children = sorted(key for key in node if key != "__declared__")
                if children:
                    schema["required"] = children
                else:
                    schema.pop("required", None)
            return schema
        children = sorted(key for key in node if key != "__declared__")
        return {
            "type": "object",
            "required": children,
            "additionalProperties": False,
            "properties": {
                child: render(node[child], (*prefix, child)) for child in children
            },
        }

    return render(tree, ())


_STRING = {"type": "string", "minLength": 1}
_NULLABLE_STRING = {"type": ["string", "null"]}
_STRING_ARRAY = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
}
_EVENT_ALIAS_SCHEMAS: dict[str, Mapping[str, Any]] = {
    "artifact_refs": _STRING_ARRAY,
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "credential_names": _STRING_ARRAY,
    "effects": _STRING_ARRAY,
    "evidence_refs": _STRING_ARRAY,
    "failed_postconditions": _STRING_ARRAY,
    "failure_class": _STRING,
    "index_ref": _NULLABLE_STRING,
    "members": {"type": "array"},
    "organization_receipt": {"type": "object"},
    "owner": _NULLABLE_STRING,
    "postconditions": _STRING_ARRAY,
    "presentation": {
        "type": "object",
        "required": ["markdown"],
        "additionalProperties": False,
        "properties": {"markdown": _NULLABLE_STRING},
    },
    "prompt_version": _NULLABLE_STRING,
    "reason": _STRING,
    "recoverable": {"type": "boolean"},
    "response_refs": _STRING_ARRAY,
    "result_ref": _NULLABLE_STRING,
    "selected_at": _STRING,
    "verification_refs": _STRING_ARRAY,
    "visibility": {"enum": ["private", "public"]},
}


def _context_schema_at_path(
    context_schema: Mapping[str, Any], path: tuple[str, ...]
) -> Mapping[str, Any]:
    if path and path[0] in _EVENT_ALIAS_SCHEMAS:
        node = _EVENT_ALIAS_SCHEMAS[path[0]]
        remaining = path[1:]
    else:
        node = context_schema
        remaining = path
    for part in remaining:
        node = _resolve_schema_ref(node, context_schema)
        properties = node.get("properties")
        if not isinstance(properties, Mapping) or not isinstance(
            properties.get(part), Mapping
        ):
            raise ControllerRuntimeError(
                f"event contract references unknown context schema path {'.'.join(path)}"
            )
        node = properties[part]
    return node


def _resolve_schema_ref(
    schema: Mapping[str, Any], context_schema: Mapping[str, Any]
) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    if not reference.startswith("#/"):
        raise ControllerRuntimeError(f"unsupported event schema reference {reference}")
    target: Any = context_schema
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, Mapping) or part not in target:
            raise ControllerRuntimeError(f"unresolved event schema reference {reference}")
        target = target[part]
    if not isinstance(target, Mapping):
        raise ControllerRuntimeError(f"event schema reference is not an object: {reference}")
    return target


def _materialize_schema_refs(
    schema: Mapping[str, Any], context_schema: Mapping[str, Any]
) -> dict[str, Any]:
    resolved = _resolve_schema_ref(schema, context_schema)
    materialized: dict[str, Any] = {}
    for key, value in resolved.items():
        if key == "$ref":
            continue
        if isinstance(value, Mapping):
            materialized[key] = _materialize_schema_refs(value, context_schema)
        elif isinstance(value, list):
            materialized[key] = [
                _materialize_schema_refs(item, context_schema)
                if isinstance(item, Mapping)
                else copy.deepcopy(item)
                for item in value
            ]
        else:
            materialized[key] = copy.deepcopy(value)
    return materialized


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


def _resolve_guard_values(event: ControllerEvent) -> dict[GuardId, bool]:
    """Derive security-sensitive lifecycle guards from typed payloads, not caller claims."""

    values = dict(event.guards)
    status_guard = GuardId("released_candidate_is_unpublished")
    values[status_guard] = _path_value(event.payload, "candidate.publication_status") == "unpublished"

    captured_birth = _path_value(event.payload, "birth.sha256")
    receipt_birth = _path_value(event.payload, "publication.birth_sha256")
    matching_birth = (
        isinstance(captured_birth, str)
        and bool(captured_birth)
        and captured_birth == receipt_birth
    )
    visibility = _path_value(event.payload, "visibility")
    values[GuardId("private_publication_matches_captured_birth")] = (
        visibility == "private" and matching_birth
    )
    values[GuardId("public_publication_matches_captured_birth")] = (
        visibility == "public" and matching_birth
    )
    owner_resolution = _path_value(event.payload, "publication.owner_resolution")
    selected_owner = _path_value(event.payload, "publication.owner")
    values[GuardId("public_owner_is_resolved")] = (
        owner_resolution == "resolved"
        and isinstance(selected_owner, str)
        and bool(selected_owner)
    )
    values[GuardId("public_owner_choice_is_required")] = (
        owner_resolution == "choice_required"
    )
    values[GuardId("exact_published_version_is_indexed")] = (
        event.id == EventId("play_indexed")
        and isinstance(_path_value(event.payload, "publication.canonical_reference"), str)
        and isinstance(_path_value(event.payload, "play.version"), str)
        and isinstance(_path_value(event.payload, "index_ref"), str)
    )
    private_org = _path_value(event.payload, "publication.private_org")
    private_owner = event.payload.get("owner")
    private_members = event.payload.get("members")
    private_evidence = event.payload.get("evidence_refs")
    private_receipt = event.payload.get("organization_receipt")
    values[GuardId("private_org_policy_satisfied")] = (
        event.id == EventId("private_org_ready")
        and isinstance(private_org, str)
        and bool(private_org)
        and isinstance(private_owner, str)
        and bool(private_owner)
        and isinstance(private_members, list)
        and _private_owner_is_member(private_owner, private_members)
        and isinstance(private_evidence, list)
        and any(isinstance(ref, str) and bool(ref) for ref in private_evidence)
        and isinstance(private_receipt, Mapping)
        and private_receipt.get("schema") == "play.rote-org-receipt/v1"
        and private_receipt.get("specialist") == "rote-org"
        and private_receipt.get("operation") == "ensure_private_org"
        and private_receipt.get("ok") is True
        and private_receipt.get("private_org") == private_org
        and private_receipt.get("owner") == private_owner
        and private_receipt.get("members") == private_members
        and private_receipt.get("evidence_refs") == private_evidence
    )
    return values


def _private_owner_is_member(owner: str, members: list[Any]) -> bool:
    for member in members:
        if member == owner:
            return True
        if not isinstance(member, Mapping):
            continue
        identity = member.get("email") or member.get("handle") or member.get("owner")
        role = member.get("role")
        if identity == owner and role in {"owner", "admin"}:
            return True
    return False


def _derive_session_guards(
    session: RuntimeSession, event: ControllerEvent
) -> ControllerEvent:
    """Resolve guards that are deterministic from harness-owned session context."""

    values = dict(event.guards)
    context = session.context
    onboarding_intent = _path_value(context, "onboarding.intent")
    values[GuardId("onboarding_is_greeting")] = onboarding_intent == "greeting"
    values[GuardId("onboarding_is_play_uri")] = onboarding_intent == "play_uri"
    values[GuardId("use_is_onboarding_starter")] = (
        _path_value(context, "onboarding.starter_status") == "selected"
    )
    values[GuardId("awareness_snapshot_ready")] = (
        _path_value(context, "awareness.complete") is True
        and isinstance(_path_value(context, "awareness.play_choices"), list)
        and bool(_path_value(context, "awareness.play_choices"))
    )
    values[GuardId("search_is_complete")] = (
        _path_value(event.payload, "search.complete") is True
    )
    values[GuardId("search_only_requested")] = (
        _path_value(context, "last_event.id") == "play_search_request"
    )
    values[GuardId("capture_is_active")] = (
        _path_value(event.payload, "capture.status") == "active"
        and isinstance(_path_value(event.payload, "capture.reference"), str)
        and bool(_path_value(event.payload, "capture.reference"))
        and isinstance(_path_value(event.payload, "capture.workspace"), str)
        and bool(_path_value(event.payload, "capture.workspace"))
    )
    values[GuardId("exploration_goal_is_required")] = (
        _path_value(context, "exploration.goal_status") == "required"
    )
    values[GuardId("exploration_goal_is_ready")] = (
        _path_value(context, "exploration.goal_status") == "ready"
        and isinstance(_path_value(context, "exploration.goal"), str)
        and bool(_path_value(context, "exploration.goal"))
    )
    values[GuardId("match_satisfies_constraints")] = (
        event.id == EventId("full_match")
        and isinstance(_path_value(event.payload, "match.reference"), str)
        and _path_value(event.payload, "match.uncovered") == []
    )
    selected_reference = _path_value(context, "match.reference")
    choices = _path_value(context, "search.play_choices")
    values[GuardId("search_has_remaining_choices")] = (
        isinstance(choices, list)
        and any(
            isinstance(choice, Mapping)
            and isinstance(choice.get("reference"), str)
            and choice.get("reference") != selected_reference
            for choice in choices
        )
    )
    values[GuardId("explore_is_approved")] = (
        _path_value(context, "consent.explore") == "approved"
    )
    allowed = _path_value(context, "modality_policy.allowed")
    modalities = _path_value(event.payload, "route.modalities")
    if isinstance(allowed, list) and isinstance(modalities, list):
        values[GuardId("route_within_policy")] = set(modalities) <= set(allowed)
    attempts = _path_value(context, "execution.attempts")
    budget = _path_value(context, "execution.budget")
    if isinstance(attempts, int) and isinstance(budget, int):
        values[GuardId("exploration_budget_remaining")] = attempts < budget
    values[GuardId("captured_trajectory_is_verified")] = (
        _path_value(context, "capture.status") == "verified"
        and isinstance(_path_value(context, "capture.reference"), str)
        and bool(_path_value(context, "capture.reference"))
        and _path_value(context, "capture.workspace")
        == _path_value(context, "execution.workspace")
        and _path_value(context, "capture.trajectory_ref")
        == _path_value(context, "evidence.verification")
    )
    values[GuardId("authentication_is_static")] = (
        _path_value(context, "authentication.classified_rung") == "static"
    )
    values[GuardId("save_choice_private")] = (
        _path_value(context, "consent.save") == "private"
    )
    values[GuardId("save_choice_public")] = (
        _path_value(context, "consent.save") == "public"
    )
    inspected_hash = _path_value(event.payload, "publication.content_hash")
    captured_hash = _path_value(context, "birth.registry_content_hash")
    matching_content = (
        isinstance(inspected_hash, str)
        and bool(inspected_hash)
        and inspected_hash == captured_hash
    )
    values[GuardId("saved_public_inspection_matches_publication")] = (
        _path_value(event.payload, "publication.visibility") == "public"
        and matching_content
    )
    values[GuardId("saved_inspection_matches_publication")] = matching_content
    return ControllerEvent(
        id=event.id,
        payload=event.payload,
        guards=values,
    )


def _validate_event_payload(
    payload: Mapping[str, Any],
    required: tuple[str, ...],
    context_schema: Mapping[str, Any],
) -> None:
    missing = [path for path in required if not _has_path(payload, path)]
    if missing:
        raise ControllerRuntimeError(
            "event payload is missing required fields: " + ", ".join(missing)
        )
    undeclared = sorted(
        path
        for path in _payload_leaf_paths(payload)
        if not any(path == allowed or path.startswith(allowed + ".") for allowed in required)
    )
    if undeclared:
        raise ControllerRuntimeError(
            "event payload contains undeclared fields: " + ", ".join(undeclared)
        )
    errors = sorted(
        Draft202012Validator(
            _event_payload_schema(required, context_schema)
        ).iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(map(str, first.path)) or "payload"
        raise ControllerRuntimeError(
            f"event payload violates schema at {location}: {first.message}"
        )


def _payload_leaf_paths(value: Any, prefix: str = "") -> list[str]:
    """Return concrete payload paths while treating declared object roots as open values."""

    if isinstance(value, Mapping):
        if not value:
            return [prefix] if prefix else []
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_payload_leaf_paths(child, child_path))
        return paths
    return [prefix] if prefix else []


def _has_path(payload: Mapping[str, Any], path: str) -> bool:
    if path in payload:
        return True
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


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
