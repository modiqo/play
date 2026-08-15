"""Execute one approved registry Play exactly once and emit its typed result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .private_store import ensure_private_directory
from .state_home import state_path


class PlayRunError(ValueError):
    """The approved Play run contract is missing or inconsistent."""


def execute(payload: Mapping[str, Any]) -> dict[str, Any]:
    match = _mapping(payload.get("match"), "match")
    inspection = _mapping(payload.get("inspection"), "inspection")
    request = _mapping(payload.get("request"), "request")
    auth_repair = _mapping(payload.get("auth_repair"), "auth_repair")
    packet = _mapping(auth_repair.get("original_packet"), "auth_repair.original_packet")
    output_policy = _mapping(payload.get("output_policy"), "output_policy")
    if output_policy.get("mode") != "detailed":
        raise PlayRunError("output_policy.mode must be detailed")
    if output_policy.get("overflow") != "artifact":
        raise PlayRunError("output_policy.overflow must be artifact")
    max_inline_bytes = output_policy.get("max_inline_bytes")
    if (
        not isinstance(max_inline_bytes, int)
        or isinstance(max_inline_bytes, bool)
        or max_inline_bytes < 1
    ):
        raise PlayRunError("output_policy.max_inline_bytes must be a positive integer")

    reference = _string(match.get("reference"), "match.reference")
    exact_reference = _string(
        inspection.get("exact_reference"), "inspection.exact_reference"
    )
    disclosure_sha256 = _string(
        inspection.get("disclosure_sha256"), "inspection.disclosure_sha256"
    )
    parameters = request.get("parameters")
    if not isinstance(parameters, Mapping):
        raise PlayRunError("request.parameters must be an object")
    if packet.get("exact_reference") != exact_reference:
        raise PlayRunError("prepared run reference differs from inspected reference")
    if packet.get("disclosure_sha256") != disclosure_sha256:
        raise PlayRunError("prepared disclosure digest differs from inspection")
    if packet.get("parameters") != dict(parameters):
        raise PlayRunError("prepared parameters differ from approved parameters")

    target = _latest_execution_target(reference)
    if target is None:
        target = _latest_execution_target(exact_reference)
    if target is None:
        raise PlayRunError("approved Play target is not a canonical URI or registry reference")
    executable = shutil.which("rote")
    if executable is None:
        raise PlayRunError("rote is not available on PATH")
    arguments = [
        executable,
        "play",
        "run",
        target,
        *[
            f"{name}={_parameter(value)}"
            for name, value in sorted(parameters.items())
        ],
        "--yes",
    ]
    environment = os.environ.copy()
    environment.setdefault("ROTE_FLOW_PROGRESS", "0")
    environment.setdefault("ROTE_NO_HINTS", "1")
    # `rote play run` owns no JSON flag. Pin its documented structured marker
    # mode so an inherited human-output preference cannot hide the typed
    # @@authentication section from this non-interactive controller boundary.
    environment["ROTE_OUTPUT_MODE"] = "structured"
    with tempfile.TemporaryDirectory(prefix="play-run-") as directory:
        stdout_path = Path(directory) / "stdout"
        stderr_path = Path(directory) / "stderr"
        try:
            with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
                completed = subprocess.run(
                    arguments,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    check=False,
                    timeout=3600,
                    env=environment,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            return _failed(str(error))

        stdout_value = _completed_bytes(completed.stdout, stdout_path)
        stderr_value = _completed_bytes(completed.stderr, stderr_path)
        if completed.returncode != 0:
            failure_output = _combined_output(
                _bounded_text(stdout_value, stdout_path, 10_000),
                _bounded_text(stderr_value, stderr_path, 10_000),
            )
            auth_failure = _typed_auth_failure(failure_output)
            if auth_failure is not None:
                return auth_failure
            return _failed(failure_output or f"rote play run exited {completed.returncode}")

        primary_value, primary_path = (
            (stdout_value, stdout_path)
            if _stream_size(stdout_value, stdout_path) > 0
            else (stderr_value, stderr_path)
        )
        primary_bytes = _stream_size(primary_value, primary_path)
        if primary_bytes == 0:
            return _failed("rote play run returned no output")
        digest = _stream_sha256(primary_value, primary_path)
        truncated = primary_bytes > max_inline_bytes
        full_output_ref = None
        artifact_refs: list[str] = []
        if truncated:
            artifact_path = _persist_full_output(primary_value, primary_path, digest)
            full_output_ref = f"file:{artifact_path}"
            artifact_refs.append(full_output_ref)
            primary = _bounded_text(primary_value, primary_path, max_inline_bytes)
        else:
            primary = _bounded_text(primary_value, primary_path, max_inline_bytes)

    version = exact_reference.rsplit("@", 1)[-1]
    local_change = inspection.get("local_change")
    manifest = {"response_refs": [], "artifact_refs": artifact_refs, "effects": []}
    return {
        "schema": "play.run-result/v1",
        "ok": True,
        "event": "play_run_ready",
        "target": target,
        "play": {"version": version},
        "resolution": {
            "local_state": "exact_ready",
            "pull_performed": local_change != "none",
        },
        "result_ref": f"sha256:{digest}",
        "response_refs": [],
        "artifact_refs": artifact_refs,
        "effects": [],
        "output": {
            "mode": "detailed",
            "detail": "full",
            "source": "rote_human_presentation",
            "format": "text",
            "primary": primary,
            "manifest": manifest,
            "truncated": truncated,
            "full_output_ref": full_output_ref,
        },
    }


def _completed_bytes(value: object, path: Path) -> bytes | None:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    return None


def _stream_size(value: bytes | None, path: Path) -> int:
    return len(value) if value is not None else path.stat().st_size


def _bounded_text(value: bytes | None, path: Path, limit: int) -> str:
    if value is None:
        with path.open("rb") as handle:
            value = handle.read(limit)
    else:
        value = value[:limit]
    return value.decode("utf-8", errors="ignore")


def _stream_sha256(value: bytes | None, path: Path) -> str:
    digest = hashlib.sha256()
    if value is not None:
        digest.update(value)
    else:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _persist_full_output(value: bytes | None, path: Path, digest: str) -> Path:
    root = state_path("run-output")
    ensure_private_directory(root)
    target = root / f"{digest}.txt"
    temporary = root / f".{digest}.{os.getpid()}.tmp"
    try:
        with temporary.open("wb") as handle:
            if value is not None:
                handle.write(value)
            else:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


_DRIFT_MARKERS = ("drift", "hash mismatch", "fingerprint mismatch", "disclosure mismatch")
_LOGIN_MARKERS = ("not logged in", "rote login", "requires login", "authentication required")


def _failed(reason: str) -> dict[str, Any]:
    """Classify a failed run honestly instead of calling every failure drift.

    ``play_drifted`` is reserved for evidence that the artifact changed after
    inspection. A registry sign-in failure names its remedy. Everything else is
    ``action_blocked`` carrying rote's own words — the reason must never be
    laundered into a narrative the evidence does not support.
    """

    bounded = reason.strip()[:20_000] or "rote play run failed"
    digest = hashlib.sha256(bounded.encode()).hexdigest()
    lowered = bounded.casefold()
    if any(marker in lowered for marker in _DRIFT_MARKERS):
        return {
            "schema": "play.run-result/v1",
            "ok": False,
            "event": "play_drifted",
            "reason": bounded,
            "evidence_refs": [f"sha256:{digest}"],
        }
    if any(marker in lowered for marker in _LOGIN_MARKERS):
        bounded = (
            "rote registry login is required before this Play can be pulled and run. "
            "Sign in with `rote login` (or the rote-setup skill), then retry this exact "
            "Play. Original error: " + bounded
        )[:20_000]
    return {
        "schema": "play.run-result/v1",
        "ok": False,
        "event": "action_blocked",
        "reason": bounded,
        "recoverable": True,
        "owner": "play",
        "evidence_refs": [f"sha256:{digest}"],
    }


def _typed_auth_failure(output: str) -> dict[str, Any] | None:
    sources: list[Mapping[str, Any]] = []
    candidates = dict.fromkeys((output, *reversed(output.splitlines())))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != 1
            or value.get("ok") is not False
        ):
            continue
        data = value.get("data")
        if not isinstance(data, Mapping):
            continue
        source = data.get("play_auth_required")
        if isinstance(source, Mapping):
            sources.append(source)

    marker_source = _marker_auth_failure(output)
    if marker_source is not None:
        sources.append(marker_source)

    # Multiple typed failures in one invocation are ambiguous. Refuse to guess
    # which adapter or credential should be repaired.
    if len(sources) != 1:
        return None
    source = sources[0]
    if source.get("schema") != "play.auth-required/v1":
        return None

    adapter_id = source.get("adapter")
    env_var = source.get("credential")
    classified_rung = _auth_protocol(source.get("protocol"))
    state = source.get("state")
    remediation = source.get("remediation")
    adapter_calls_started = source.get("adapter_calls_started")
    if (
        not isinstance(adapter_id, str)
        or not adapter_id.strip()
        or not isinstance(env_var, str)
        or not env_var.strip()
        or not isinstance(state, str)
        or not state.strip()
        or not isinstance(remediation, str)
        or not remediation.strip()
        or classified_rung is None
        or state not in _AUTH_FAILURE_STATES
        or adapter_calls_started is not False
    ):
        return None

    digest = hashlib.sha256(output.encode()).hexdigest()
    return {
        "schema": "play.run-result/v1",
        "ok": False,
        "event": "play_auth_repair_required",
        "auth_repair": {
            "source": "rote_auth_repair_required",
            "owner": "rote-adapter-config",
            "recoverable": True,
            "adapter_id": adapter_id.strip(),
            "env_var": env_var.strip(),
            "classified_rung": classified_rung,
            "distinguishing_error": f"{state}: {remediation.strip()}",
            "evidence_refs": [f"sha256:{digest}"],
        },
    }


_AUTH_PROTOCOLS = {
    "static": "static",
    "oauth": "oauth",
    "oauth_dcr": "oauth_dcr",
    "google_discovery": "google_discovery",
    # Rote's marker/prose renderer deliberately uses human labels. Keep this
    # list synchronized with CredentialAcquisitionProtocol::as_str; unknown
    # values fail closed instead of being treated as a static token.
    "paste a static credential": "static",
    "adapter OAuth reauthorization": "oauth",
    "browser OAuth with dynamic registration": "oauth_dcr",
    "browser Google authorization": "google_discovery",
}
_AUTH_FAILURE_STATES = {
    "missing",
    "unreadable",
    "refresh_required",
    "reauth_required",
    "transient",
    "indeterminate",
    "unsupported",
}
_AUTH_MARKER_FIELDS = {
    "Adapter": "adapter",
    "Credential": "credential",
    "State": "state",
    "Protocol": "protocol",
    "Repair interaction": "repair_interaction",
    "Network required": "network_required",
    "Remediation": "remediation",
    "Adapter calls started": "adapter_calls_started",
}


def _auth_protocol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _AUTH_PROTOCOLS.get(value.strip())


def _marker_auth_failure(output: str) -> Mapping[str, Any] | None:
    """Project Rote's documented ``@@authentication`` section onto its v1 wire.

    The Play run command currently owns a marker/prose shell rather than a
    ``--json`` switch. Only the exact documented fields are accepted, and the
    adapter-call safety bit must be present so ordinary Play output cannot be
    mistaken for a pre-execution authentication refusal.
    """

    lines = output.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "@@authentication"
    ]
    if len(starts) != 1:
        return None
    fields: dict[str, Any] = {}
    for line in lines[starts[0] + 1 :]:
        stripped = line.strip()
        if stripped.startswith("@@"):
            break
        if not stripped or ": " not in stripped:
            continue
        label, value = stripped.split(": ", 1)
        field = _AUTH_MARKER_FIELDS.get(label)
        if field is None or field in fields:
            continue
        fields[field] = value.strip()
    required = set(_AUTH_MARKER_FIELDS.values())
    if set(fields) != required:
        return None
    if fields["network_required"] not in {"yes", "no"}:
        return None
    if fields["adapter_calls_started"] not in {"true", "false"}:
        return None
    fields["network_required"] = fields["network_required"] == "yes"
    fields["adapter_calls_started"] = fields["adapter_calls_started"] == "true"
    fields["schema"] = "play.auth-required/v1"
    return fields


def _canonical_play_uri(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    segments = [segment for segment in parsed.path.split("/") if segment]
    return (
        parsed.scheme == "https"
        and parsed.hostname == "play.modiqo.ai"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and len(segments) == 2
    )


def _latest_execution_target(value: str) -> str | None:
    """Return the canonical latest-release selector for a Play reference."""

    if _canonical_play_uri(value):
        parsed = urlparse(value)
        owner, name = [segment for segment in parsed.path.split("/") if segment]
        name = name.partition("@")[0]
        return f"https://play.modiqo.ai/{owner}/{name}"
    owner_name = value.partition("@")[0]
    if owner_name.count("/") != 1:
        return None
    owner, name = owner_name.split("/", 1)
    if not owner or not name:
        return None
    return owner_name


def _parameter(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _combined_output(stdout: str, stderr: str) -> str:
    parts = [part.rstrip() for part in (stdout, stderr) if part.strip()]
    return "\n".join(parts)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlayRunError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlayRunError(f"{label} must be a non-empty string")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--json", action="store_true")
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise PlayRunError("stdin must contain an object")
        result = execute(payload)
    except (json.JSONDecodeError, PlayRunError) as error:
        parser.exit(1, f"play-run: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
