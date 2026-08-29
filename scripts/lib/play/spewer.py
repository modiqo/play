"""Durable Play-side inbox for Spewer task receipts.

Spewer owns execution and at-least-once result delivery. This adapter owns the
private association between a Play run and a Spewer task. It never sends or
prints Play's continuation reference through the Spewer protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol, Sequence

from .state_home import state_path


SCHEMA = "play.spewer-adapter/v1"
CONSUMER_ID = "play"
TERMINAL = {"completed", "failed", "cancelled", "escalated"}


class SpewerAdapterError(ValueError):
    """The adapter, its durable state, or Spewer violated the contract."""


class SpewerTransport(Protocol):
    """Small service surface required by the durable adapter."""

    def capabilities(self) -> Mapping[str, Any]: ...

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def observe(self, task_id: str, after: int) -> Mapping[str, Any]: ...

    def result(self, task_id: str) -> Mapping[str, Any]: ...

    def acknowledge(self, message_id: str, consumer_id: str) -> bool: ...


class SpewerClient:
    """One-request-per-connection client for Spewer's private Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path

    def capabilities(self) -> Mapping[str, Any]:
        return self._payload("capabilities", "capabilities")

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._payload("submit", "handle", request=request)

    def observe(self, task_id: str, after: int) -> Mapping[str, Any]:
        return self._payload("observe", "observation", task_id=task_id, after=after)

    def result(self, task_id: str) -> Mapping[str, Any]:
        return self._payload("result", "result", task_id=task_id)

    def acknowledge(self, message_id: str, consumer_id: str) -> bool:
        response = self._call(
            {"op": "acknowledge", "message_id": message_id, "consumer_id": consumer_id}
        )
        if response.get("type") != "acknowledged" or not isinstance(
            response.get("applied"), bool
        ):
            raise SpewerAdapterError("Spewer returned an invalid acknowledgement")
        return bool(response["applied"])

    def _payload(self, operation: str, response_type: str, **fields: Any) -> Mapping[str, Any]:
        response = self._call({"op": operation, **fields})
        if response.get("type") != response_type:
            raise SpewerAdapterError(
                f"Spewer returned {response.get('type')!r} for {operation}"
            )
        payload = response.get(response_type)
        if not isinstance(payload, Mapping):
            raise SpewerAdapterError(f"Spewer omitted {response_type}")
        return payload

    def _call(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        encoded = _canonical_json(request).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(10)
                stream.connect(str(self.socket_path))
                stream.sendall(encoded)
                response = _read_line(stream, 1_048_576)
        except OSError as error:
            raise SpewerAdapterError(f"cannot reach Spewer at {self.socket_path}: {error}") from error
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as error:
            raise SpewerAdapterError(f"Spewer returned invalid JSON: {error}") from error
        if not isinstance(payload, Mapping):
            raise SpewerAdapterError("Spewer response must be an object")
        if payload.get("type") == "error":
            raise SpewerAdapterError(
                f"Spewer rejected the request: {payload.get('kind')}: {payload.get('message')}"
            )
        return payload


class SpewerAdapter:
    """Durable submit, observe, inbox, claim, and acknowledge state machine."""

    def __init__(
        self,
        transport: SpewerTransport,
        *,
        database_path: Path | None = None,
        consumer_id: str = CONSUMER_ID,
    ) -> None:
        self.transport = transport
        self.database_path = database_path or state_path("spewer/adapter.sqlite")
        self.consumer_id = consumer_id
        self._migrate()

    def submit(
        self,
        *,
        host_run_id: str,
        continuation_ref: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = _normalize_request(request, self.consumer_id)
        request_hash = _request_hash(normalized)
        job_id = "psj_" + _digest(f"{host_run_id}:{request_hash}")[:24]
        encoded = _canonical_json(normalized)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT job_id, request_hash, request_json, task_id, continuation_ref "
                "FROM jobs WHERE host_run_id = ?",
                (host_run_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO jobs(job_id, host_run_id, continuation_ref, request_hash, "
                    "request_json, status, cursor, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'prepared', 0, ?, ?)",
                    (job_id, host_run_id, continuation_ref, request_hash, encoded, _now(), _now()),
                )
            elif existing[1] != request_hash or existing[2] != encoded:
                raise SpewerAdapterError("host_run_id is already bound to another Spewer request")
            elif existing[0] != job_id:
                raise SpewerAdapterError("stored adapter job identity is inconsistent")
            elif existing[4] != continuation_ref:
                raise SpewerAdapterError(
                    "host_run_id is already bound to another Play continuation"
                )
            elif existing[3] is not None:
                return self._public_job(connection, job_id)

        self._check_capabilities()
        handle = self.transport.submit(normalized)
        task_id = _text(handle, "task_id")
        cursor = _integer(handle, "event_cursor")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE jobs SET task_id = ?, cursor = ?, status = 'submitted', "
                "updated_at = ? WHERE job_id = ?",
                (task_id, cursor, _now(), job_id),
            )
            return self._public_job(connection, job_id)

    def poll(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        if job["status"] in {"ready", "claimed", "applied", "acknowledged"}:
            return self.status(job_id)
        task_id = _required(job, "task_id")
        observation = self.transport.observe(task_id, int(job["cursor"]))
        cursor = _integer(observation, "next_cursor")
        projection = _mapping(observation, "projection")
        events = observation.get("events")
        if not isinstance(events, list):
            raise SpewerAdapterError("Spewer observation omitted events")
        status = _text(projection, "status")
        result = self.transport.result(task_id) if status in TERMINAL else None
        message = result.get("message") if isinstance(result, Mapping) else None
        with self._transaction() as connection:
            connection.execute(
                "UPDATE jobs SET cursor = ?, status = ?, updated_at = ? WHERE job_id = ?",
                (cursor, "submitted" if message is None else "ready", _now(), job_id),
            )
            if message is not None:
                if not isinstance(message, Mapping):
                    raise SpewerAdapterError("Spewer terminal message is malformed")
                self._store_message(connection, job_id, message)
            public = self._public_job(connection, job_id)
        public["events"] = events
        public["projection"] = dict(projection)
        public["poll_after_ms"] = observation.get("poll_after_ms", 500)
        return public

    def claim(self, job_id: str, claim_id: str) -> dict[str, Any]:
        """Idempotently claim one receipt without exposing the continuation reference."""

        claimed = self._claim(job_id, claim_id)
        claimed.pop("continuation_ref", None)
        return claimed

    def trusted_claim(self, job_id: str, claim_id: str) -> dict[str, Any]:
        """Claim for an in-process Play host that already owns continuation state."""

        return self._claim(job_id, claim_id)

    def complete(self, job_id: str, claim_id: str) -> dict[str, Any]:
        """Record host application, then retry Spewer acknowledgement to completion."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT claim_id, message_id, status FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise SpewerAdapterError("adapter job does not exist")
            if row[0] != claim_id:
                raise SpewerAdapterError("claim_id does not own this receipt")
            if row[2] not in {"claimed", "applied", "acknowledged"}:
                raise SpewerAdapterError("receipt must be claimed before completion")
            message_id = str(row[1])
            if row[2] != "acknowledged":
                connection.execute(
                    "UPDATE jobs SET status = 'applied', updated_at = ? WHERE job_id = ?",
                    (_now(), job_id),
                )
        self.transport.acknowledge(message_id, self.consumer_id)
        with self._transaction() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'acknowledged', updated_at = ? WHERE job_id = ?",
                (_now(), job_id),
            )
            return self._public_job(connection, job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            return self._public_job(connection, job_id)

    def pending(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            identifiers = connection.execute(
                "SELECT job_id FROM jobs WHERE status != 'acknowledged' ORDER BY created_at"
            ).fetchall()
            return [self._public_job(connection, str(row[0])) for row in identifiers]

    def _claim(self, job_id: str, claim_id: str) -> dict[str, Any]:
        if not claim_id.strip():
            raise SpewerAdapterError("claim_id must not be empty")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT j.status, j.claim_id, j.continuation_ref, i.payload_json "
                "FROM jobs j LEFT JOIN inbox i ON i.job_id = j.job_id WHERE j.job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise SpewerAdapterError("adapter job does not exist")
            if row[0] == "ready":
                connection.execute(
                    "UPDATE jobs SET status = 'claimed', claim_id = ?, updated_at = ? "
                    "WHERE job_id = ?",
                    (claim_id, _now(), job_id),
                )
            elif row[0] not in {"claimed", "applied", "acknowledged"}:
                raise SpewerAdapterError("terminal receipt is not ready to claim")
            elif row[1] != claim_id:
                raise SpewerAdapterError("receipt is already owned by another claim_id")
            if not isinstance(row[3], str):
                raise SpewerAdapterError("durable receipt inbox is empty")
            message = json.loads(row[3])
            receipt = _mapping(message, "receipt")
            token = "psr_" + _digest(f"{job_id}:{claim_id}:{_text(receipt, 'receipt_id')}")[:24]
            return {
                "schema": SCHEMA,
                "job_id": job_id,
                "status": "claimed",
                "resume_token": token,
                "continuation_ref": str(row[2]),
                "receipt": dict(receipt),
            }

    def _store_message(
        self, connection: sqlite3.Connection, job_id: str, message: Mapping[str, Any]
    ) -> None:
        message_id = _text(message, "message_id")
        receipt = _mapping(message, "receipt")
        receipt_id = _text(receipt, "receipt_id")
        encoded = _canonical_json(message)
        existing = connection.execute(
            "SELECT payload_json FROM inbox WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if existing is not None and existing[0] != encoded:
            raise SpewerAdapterError("receipt_id was redelivered with different contents")
        connection.execute(
            "INSERT OR IGNORE INTO inbox(receipt_id, job_id, message_id, payload_json, received_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (receipt_id, job_id, message_id, encoded, _now()),
        )
        connection.execute(
            "UPDATE jobs SET receipt_id = ?, message_id = ? WHERE job_id = ?",
            (receipt_id, message_id, job_id),
        )

    def _check_capabilities(self) -> None:
        capabilities = self.transport.capabilities()
        operations = capabilities.get("operations")
        required = {"submit", "observe", "result", "acknowledge"}
        if not isinstance(operations, list) or not required.issubset(set(operations)):
            raise SpewerAdapterError("Spewer lacks the durable adapter operation set")

    def _job(self, job_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT task_id, cursor, status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise SpewerAdapterError("adapter job does not exist")
        return {"task_id": row[0], "cursor": row[1], "status": row[2]}

    def _public_job(self, connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT host_run_id, task_id, cursor, status, receipt_id, message_id, updated_at "
            "FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise SpewerAdapterError("adapter job does not exist")
        return {
            "schema": SCHEMA,
            "job_id": job_id,
            "host_run_id": row[0],
            "task_id": row[1],
            "cursor": row[2],
            "status": row[3],
            "receipt_id": row[4],
            "message_id": row[5],
            "updated_at": row[6],
        }

    def _migrate(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path.parent.chmod(0o700)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                PRAGMA foreign_keys = ON;
                PRAGMA busy_timeout = 5000;
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    host_run_id TEXT NOT NULL UNIQUE,
                    continuation_ref TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    task_id TEXT UNIQUE,
                    cursor INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    receipt_id TEXT UNIQUE,
                    message_id TEXT UNIQUE,
                    claim_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox (
                    receipt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE,
                    message_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
                );
                """
            )
        self.database_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _normalize_request(request: Mapping[str, Any], consumer_id: str) -> dict[str, Any]:
    normalized = json.loads(_canonical_json(request))
    if normalized.get("private_continuation") is not None:
        raise SpewerAdapterError("Play continuation state must not enter a Spewer request")
    callback = normalized.get("callback")
    if not isinstance(callback, dict):
        raise SpewerAdapterError("Spewer request requires a callback object")
    callback["mode"] = "poll"
    callback["consumer_id"] = consumer_id
    if not isinstance(normalized.get("idempotency_key"), str):
        raise SpewerAdapterError("Spewer request requires idempotency_key")
    return normalized


def _request_hash(request: Mapping[str, Any]) -> str:
    canonical = dict(request)
    canonical["task_id"] = None
    return _digest(_canonical_json(canonical))


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_line(stream: socket.socket, limit: int) -> str:
    data = bytearray()
    while len(data) <= limit:
        chunk = stream.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
    if not data or len(data) > limit:
        raise SpewerAdapterError("Spewer response is empty or exceeds 1 MiB")
    return bytes(data).split(b"\n", 1)[0].decode()


def _mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise SpewerAdapterError(f"{field} must be an object")
    return value


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise SpewerAdapterError(f"{field} must be a non-empty string")
    return value


def _integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SpewerAdapterError(f"{field} must be a nonnegative integer")
    return value


def _required(payload: Mapping[str, Any], field: str) -> str:
    return _text(payload, field)


def _load_request(path: str) -> Mapping[str, Any]:
    try:
        payload = json.load(sys.stdin) if path == "-" else json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SpewerAdapterError(f"cannot load task request: {error}") from error
    if not isinstance(payload, Mapping):
        raise SpewerAdapterError("task request must be a JSON object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Durable Play adapter for Spewer",
        epilog=(
            "State machine: submit -> poll/watch -> claim -> resume Play -> complete. "
            "Only complete acknowledges Spewer, after the harness confirms resumption."
        ),
    )
    parser.add_argument("--socket", type=Path, default=_default_socket())
    parser.add_argument("--state", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser(
        "submit",
        help="persist intent, then submit idempotently",
        description=(
            "Use after Play classifies one bounded task. State: absent -> prepared -> "
            "submitted. Next: save job_id, then run poll or watch. Output is one JSON job."
        ),
    )
    submit.add_argument("--host-run-id", required=True)
    submit.add_argument("--continuation-ref", required=True)
    submit.add_argument("--request", required=True, help="task JSON path, or - for stdin")
    poll = commands.add_parser(
        "poll",
        help="advance the durable cursor once",
        description=(
            "Use for one nonblocking observation. State: submitted -> submitted or ready. "
            "Next: wait poll_after_ms, poll again, or claim a ready receipt."
        ),
    )
    poll.add_argument("job_id")
    watch = commands.add_parser(
        "watch",
        help="poll until a receipt is durable",
        description=(
            "Use when this process may wait. State: submitted -> ready. Next: claim the "
            "receipt with one stable host claim ID. Spewer controls the polling delay."
        ),
    )
    watch.add_argument("job_id")
    watch.add_argument("--interval", type=float, default=0.5)
    watch.add_argument("--timeout", type=float, default=300)
    claim = commands.add_parser(
        "claim",
        help="claim one receipt idempotently",
        description=(
            "Use after poll or watch returns ready. State: ready -> claimed. Next: resume "
            "Play with the receipt, then run complete with the same claim ID."
        ),
    )
    claim.add_argument("job_id")
    claim.add_argument("--claim-id", required=True)
    complete = commands.add_parser(
        "complete",
        help="record successful resume, then acknowledge Spewer",
        description=(
            "Use only after Play durably accepts the claimed receipt. State: claimed -> "
            "applied -> acknowledged. Next: stop on acknowledged, or retry with the same "
            "claim ID after any lost response."
        ),
    )
    complete.add_argument("job_id")
    complete.add_argument("--claim-id", required=True)
    status = commands.add_parser(
        "status",
        help="show one adapter job without private state",
        description=(
            "Use during recovery. State: unchanged. Next follows the returned status: "
            "poll submitted, claim ready, or complete claimed/applied work."
        ),
    )
    status.add_argument("job_id")
    commands.add_parser(
        "pending",
        help="list work not yet acknowledged",
        description=(
            "Use after a host restart. State: unchanged. Next: resume each returned job "
            "from its status; acknowledged jobs are omitted."
        ),
    )
    return parser


def _default_socket() -> Path:
    root = os.environ.get("SPEWER_HOME")
    return Path(root) / "spewer.sock" if root else Path.home() / ".local/share/spewer/spewer.sock"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    adapter = SpewerAdapter(
        SpewerClient(args.socket),
        database_path=args.state,
    )
    try:
        if args.command == "submit":
            output: object = adapter.submit(
                host_run_id=args.host_run_id,
                continuation_ref=args.continuation_ref,
                request=_load_request(args.request),
            )
        elif args.command == "poll":
            output = adapter.poll(args.job_id)
        elif args.command == "watch":
            deadline = time.monotonic() + args.timeout
            while True:
                output = adapter.poll(args.job_id)
                if output.get("status") == "ready":
                    break
                if time.monotonic() >= deadline:
                    raise SpewerAdapterError("watch timed out before a terminal receipt")
                suggested = output.get("poll_after_ms")
                delay = (
                    float(suggested) / 1000
                    if isinstance(suggested, int) and suggested > 0
                    else args.interval
                )
                time.sleep(max(args.interval, delay))
        elif args.command == "claim":
            output = adapter.claim(args.job_id, args.claim_id)
        elif args.command == "complete":
            output = adapter.complete(args.job_id, args.claim_id)
        elif args.command == "status":
            output = adapter.status(args.job_id)
        else:
            output = adapter.pending()
    except SpewerAdapterError as error:
        print(f"play-spewer: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0
