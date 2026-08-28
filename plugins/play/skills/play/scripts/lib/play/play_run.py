"""Execute one approved registry Play and emit its typed result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .commands import CommandError, run_json
from .private_store import ensure_private_directory
from .state_home import state_path


class PlayRunError(ValueError):
    """The approved Play run contract is missing or inconsistent."""


def execute(payload: Mapping[str, Any]) -> dict[str, Any]:
    match = _mapping(payload.get("match"), "match")
    inspection = _mapping(payload.get("inspection"), "inspection")
    request = _mapping(payload.get("request"), "request")
    authentication = _mapping(payload.get("authentication"), "authentication")
    packet = _mapping(authentication.get("original_packet"), "authentication.original_packet")
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
    operations = inspection.get("operations")
    if not isinstance(operations, list):
        raise PlayRunError("inspection.operations must be an array")
    play_owns_authentication = _declares_auth_ensure(operations)
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
    # Keep step failures observable. Rote writes progress to stderr and the
    # Play result to stdout, so successful primary output remains unchanged.
    environment["ROTE_FLOW_PROGRESS"] = "1"
    environment.setdefault("ROTE_NO_HINTS", "1")
    # `rote play run` owns no JSON flag. Pin its documented structured marker
    # mode so an inherited human-output preference cannot hide the typed
    # @@authentication section from this non-interactive controller boundary.
    environment["ROTE_OUTPUT_MODE"] = "structured"
    workspace_before = _play_workspace_state(target, environment)

    # A user who already completed out-of-band static-token setup selects the
    # verification event, which returns directly to this exact approved run.
    # Confirm the manifest-declared key against Rote's token inventory before
    # invoking any provider operation or specialist.
    if (
        authentication.get("status") == "authenticating"
        and authentication.get("classified_rung") == "static"
    ):
        adapter_id = _string(
            authentication.get("adapter_id"), "authentication.adapter_id"
        )
        env_var = _string(authentication.get("env_var"), "authentication.env_var")
        distinguishing_error = _string(
            authentication.get("distinguishing_error"),
            "authentication.distinguishing_error",
        )
        static_authentication = {
            "adapter_id": adapter_id,
            "env_var": env_var,
            "classified_rung": "static",
            "distinguishing_error": distinguishing_error,
        }
        try:
            verified_static = _credential_snapshot(
                executable, adapter_id, env_var, environment
            )
        except CommandError as error:
            return _failed(
                "Play could not verify the static credential contract: " + str(error)
            )
        contract_error = _credential_contract_error(
            verified_static, adapter_id, env_var
        )
        if contract_error is not None:
            return _failed(contract_error)
        if not verified_static.usable:
            verification_error = (
                f"credential {env_var} is not present and healthy for adapter "
                f"{adapter_id}"
            )
            return _authentication_required(
                {
                    **static_authentication,
                    "distinguishing_error": verification_error,
                },
                f"Static {verification_error}; no provider call was started.",
            )
    with tempfile.TemporaryDirectory(prefix="play-run-") as directory:
        try:
            completed, stdout_path, stderr_path = _invoke(
                arguments,
                environment,
                Path(directory),
                suffix="initial",
                terminal_stdin=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return _failed(str(error))

        stdout_value = _completed_bytes(completed.stdout, stdout_path)
        stderr_value = _completed_bytes(completed.stderr, stderr_path)
        if completed.returncode != 0:
            failure_output = _combined_output(
                _bounded_edge_text(stdout_value, stdout_path, 10_000),
                _bounded_edge_text(stderr_value, stderr_path, 10_000),
            )
            auth_failure = _typed_auth_failure(failure_output)
            if auth_failure is None:
                return _failed(failure_output or f"rote play run exited {completed.returncode}")

            try:
                credential_before = _credential_snapshot(
                    executable,
                    auth_failure["adapter_id"],
                    auth_failure["env_var"],
                    environment,
                )
            except CommandError as error:
                return _failed(
                    "Play could not verify the adapter credential contract before "
                    f"authentication: {error}"
                )
            contract_error = _credential_contract_error(
                credential_before,
                auth_failure["adapter_id"],
                auth_failure["env_var"],
            )
            if contract_error is not None:
                return _failed(contract_error)

            # A static credential cannot be minted by adapter.auth.ensure. If
            # the exact manifest key is already healthy, the out-of-band token
            # handoff has completed and Play can retry the approved run once.
            # Otherwise the harness guides the user to the vendor's token page
            # and `rote token set ... --stdin`. Legacy Plays without an
            # auth.ensure declaration retain their compatibility specialist.
            if auth_failure["classified_rung"] == "static":
                if not credential_before.usable:
                    return _authentication_required(auth_failure, failure_output)
                try:
                    completed, stdout_path, stderr_path = _invoke(
                        arguments,
                        environment,
                        Path(directory),
                        suffix="credential-confirmed",
                        terminal_stdin=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    return _failed(str(error))
                stdout_value = _completed_bytes(completed.stdout, stdout_path)
                stderr_value = _completed_bytes(completed.stderr, stderr_path)
                if completed.returncode != 0:
                    failure_output = _combined_output(
                        _bounded_edge_text(stdout_value, stdout_path, 10_000),
                        _bounded_edge_text(stderr_value, stderr_path, 10_000),
                    )
                    return _failed(
                        failure_output
                        or "rote play run failed after the exact static credential "
                        "was confirmed healthy"
                    )
            elif not play_owns_authentication:
                return _authentication_required(auth_failure, failure_output)
            else:
                # The approved Play run already disclosed authentication. Give
                # the exact same Rote command a terminal-backed stdin so its
                # declared adapter.auth.ensure step owns browser authorization.
                # Play never shells out to OAuth itself or handles a secret.
                try:
                    completed, stdout_path, stderr_path = _invoke_authenticated(
                        arguments,
                        environment,
                        Path(directory),
                        auth_failure,
                        credential_before,
                    )
                except (CommandError, OSError, subprocess.TimeoutExpired) as error:
                    return _failed(str(error))
                stdout_value = _completed_bytes(completed.stdout, stdout_path)
                stderr_value = _completed_bytes(completed.stderr, stderr_path)
                if completed.returncode != 0:
                    failure_output = _combined_output(
                        _bounded_edge_text(stdout_value, stdout_path, 10_000),
                        _bounded_edge_text(stderr_value, stderr_path, 10_000),
                    )
                    return _failed(
                        failure_output
                        or f"rote play run exited {completed.returncode} after Play authentication"
                    )

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

    execution_workspace = _changed_play_workspace(
        workspace_before,
        _play_workspace_state(target, environment),
    )
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
        "execution": {"workspace": execution_workspace},
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


def _rote_workspace_root(environment: Mapping[str, str]) -> Path:
    rote_home = environment.get("ROTE_HOME")
    return (Path(rote_home) if rote_home else Path.home() / ".rote") / "rote" / "workspaces"


def _play_slug(reference: str) -> str | None:
    """Return a registry Play slug without interpreting user-controlled prose."""

    parsed = urlparse(reference)
    value = parsed.path if parsed.scheme == "https" else reference
    segments = [segment for segment in value.split("/") if segment]
    if len(segments) < 2:
        return None
    slug = segments[-1].split("@", 1)[0]
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    if not slug or any(character not in allowed for character in slug):
        return None
    return slug


def _play_workspace_state(
    reference: str,
    environment: Mapping[str, str],
) -> dict[str, tuple[int, int, int, int]]:
    """Snapshot only workspaces in Rote's deterministic ``dag-<play>-`` namespace."""

    slug = _play_slug(reference)
    root = _rote_workspace_root(environment)
    if slug is None or not root.is_dir():
        return {}
    state: dict[str, tuple[int, int, int, int]] = {}
    try:
        candidates = list(root.glob(f"dag-{slug}-*"))
    except OSError:
        return {}
    for workspace in candidates:
        database = workspace / ".rote" / "workspace.db"
        responses = workspace / ".rote" / "responses"
        try:
            database_stat = database.stat()
        except OSError:
            continue
        try:
            responses_stat = responses.stat()
        except OSError:
            responses_stat = None
        state[workspace.name] = (
            database_stat.st_mtime_ns,
            database_stat.st_size,
            responses_stat.st_mtime_ns if responses_stat is not None else 0,
            responses_stat.st_size if responses_stat is not None else 0,
        )
    return state


def _changed_play_workspace(
    before: Mapping[str, tuple[int, int, int, int]],
    after: Mapping[str, tuple[int, int, int, int]],
) -> str | None:
    """Return an exact workspace only when one run-scoped candidate changed."""

    changed = sorted(name for name, signature in after.items() if before.get(name) != signature)
    return changed[0] if len(changed) == 1 else None


def _invoke(
    arguments: Sequence[str],
    environment: Mapping[str, str],
    directory: Path,
    *,
    suffix: str,
    terminal_stdin: bool,
) -> tuple[subprocess.CompletedProcess[Any], Path, Path]:
    stdout_path = directory / f"stdout-{suffix}"
    stderr_path = directory / f"stderr-{suffix}"
    master_fd: int | None = None
    slave_fd: int | None = None
    try:
        if terminal_stdin:
            import pty

            master_fd, slave_fd = pty.openpty()
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            completed = subprocess.run(
                list(arguments),
                stdin=slave_fd,
                stdout=stdout_handle,
                stderr=stderr_handle,
                check=False,
                timeout=3600,
                env=dict(environment),
            )
    finally:
        if slave_fd is not None:
            os.close(slave_fd)
        if master_fd is not None:
            os.close(master_fd)
    return completed, stdout_path, stderr_path


@dataclass(frozen=True)
class _CredentialSnapshot:
    """Non-secret evidence for one adapter's declared credential."""

    adapter_id: str
    expected_env: str
    declared_env: str | None
    token_present: bool
    token_unreadable: bool
    healthy: bool
    health_state: str | None
    signature: str

    @property
    def usable(self) -> bool:
        return (
            self.declared_env == self.expected_env
            and self.token_present
            and not self.token_unreadable
            and self.healthy
        )


def _credential_snapshot(
    executable: str,
    adapter_id: str,
    expected_env: str,
    environment: Mapping[str, str],
) -> _CredentialSnapshot:
    """Compare the adapter manifest key with Rote's token metadata.

    Neither command exposes the credential value. The adapter health response
    supplies the manifest-declared ``token_env``; the token inventory confirms
    that the same named credential exists and is readable.
    """

    adapters_value = run_json(
        [executable, "adapter", "list", adapter_id, "--json", "--health"],
        error_type=CommandError,
        environment=dict(environment),
        timeout_seconds=10,
    )
    tokens_value = run_json(
        [executable, "token", "list", "--json"],
        error_type=CommandError,
        environment=dict(environment),
        timeout_seconds=10,
    )
    adapter = _matching_adapter(adapters_value, adapter_id)
    health = adapter.get("health")
    if not isinstance(health, Mapping):
        raise CommandError(f"adapter {adapter_id} health metadata is missing")
    declared_env_value = health.get("token_env")
    declared_env = (
        declared_env_value.strip()
        if isinstance(declared_env_value, str) and declared_env_value.strip()
        else None
    )
    token = _matching_token(tokens_value, expected_env)
    token_present = token is not None
    token_unreadable = token.get("unreadable") is True if token is not None else False
    healthy = health.get("healthy") is True
    health_state_value = health.get("state")
    health_state = (
        health_state_value.strip()
        if isinstance(health_state_value, str) and health_state_value.strip()
        else None
    )
    # Hash only metadata that cannot contain a secret. A changed signature is
    # evidence that browser authorization produced or rotated this exact key.
    token_evidence = (
        {
            key: token.get(key)
            for key in (
                "name",
                "type",
                "created",
                "expires_in",
                "refresh",
                "refresh_state",
                "is_dcr",
                "unreadable",
            )
        }
        if token is not None
        else None
    )
    evidence = {
        "adapter_id": adapter_id,
        "declared_env": declared_env,
        "expected_env": expected_env,
        "health": {"healthy": healthy, "state": health_state},
        "token": token_evidence,
    }
    signature = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return _CredentialSnapshot(
        adapter_id=adapter_id,
        expected_env=expected_env,
        declared_env=declared_env,
        token_present=token_present,
        token_unreadable=token_unreadable,
        healthy=healthy,
        health_state=health_state,
        signature=signature,
    )


def _matching_adapter(value: object, adapter_id: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CommandError("adapter health response must be an object")
    adapters = value.get("adapters")
    if not isinstance(adapters, list):
        raise CommandError("adapter health response lacks adapters")
    matches = [
        item
        for item in adapters
        if isinstance(item, Mapping) and item.get("id") == adapter_id
    ]
    if len(matches) != 1:
        raise CommandError(f"adapter health did not identify exactly one {adapter_id}")
    return matches[0]


def _matching_token(value: object, expected_env: str) -> Mapping[str, Any] | None:
    tokens: object = value
    if isinstance(value, Mapping):
        tokens = value.get("tokens")
    if not isinstance(tokens, list):
        raise CommandError("token inventory response must be an array")
    matches = [
        item
        for item in tokens
        if isinstance(item, Mapping) and item.get("name") == expected_env
    ]
    if len(matches) > 1:
        raise CommandError(f"token inventory contains duplicate {expected_env} entries")
    return matches[0] if matches else None


def _credential_contract_error(
    snapshot: _CredentialSnapshot, adapter_id: str, expected_env: str
) -> str | None:
    if snapshot.declared_env is None:
        return (
            f"Play authentication contract mismatch: adapter {adapter_id} does not "
            f"declare a credential key, but the Play run requested {expected_env}."
        )
    if snapshot.declared_env != expected_env:
        return (
            f"Play authentication contract mismatch: adapter {adapter_id} declares "
            f"{snapshot.declared_env}, but the Play run requested {expected_env}."
        )
    return None


def _credential_completed(
    before: _CredentialSnapshot, after: _CredentialSnapshot
) -> bool:
    return after.usable and (
        not before.usable or before.signature != after.signature
    )


def _invoke_authenticated(
    arguments: Sequence[str],
    environment: Mapping[str, str],
    directory: Path,
    authentication: Mapping[str, str],
    before: _CredentialSnapshot,
) -> tuple[subprocess.CompletedProcess[Any], Path, Path]:
    """Run browser authentication while observing its exact credential key.

    Rote remains the sole owner of adapter.auth.ensure and the browser flow.
    Play only observes non-secret adapter/token metadata. Once the declared key
    becomes healthy, Play closes the interactive authorization process and
    retries the exact approved command once with the verified credential. This
    avoids depending on provider-specific post-browser terminal prompts.
    """

    import pty

    stdout_path = directory / "stdout-authenticated"
    stderr_path = directory / "stderr-authenticated"
    master_fd, slave_fd = pty.openpty()
    process: subprocess.Popen[Any] | None = None
    timeout_seconds = _positive_duration(environment, "PLAY_AUTH_TIMEOUT_SECONDS", 900.0)
    poll_seconds = _positive_duration(environment, "PLAY_AUTH_POLL_SECONDS", 0.5)
    deadline = time.monotonic() + timeout_seconds
    next_probe = 0.0
    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                list(arguments),
                stdin=slave_fd,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=dict(environment),
                start_new_session=True,
            )
            os.close(slave_fd)
            slave_fd = -1
            while process.poll() is None:
                now = time.monotonic()
                if now >= deadline:
                    _stop_process_group(process)
                    raise subprocess.TimeoutExpired(list(arguments), timeout_seconds)
                if now >= next_probe:
                    after = _credential_snapshot(
                        arguments[0],
                        authentication["adapter_id"],
                        authentication["env_var"],
                        environment,
                    )
                    contract_error = _credential_contract_error(
                        after,
                        authentication["adapter_id"],
                        authentication["env_var"],
                    )
                    if contract_error is not None:
                        _stop_process_group(process)
                        raise CommandError(contract_error)
                    if _credential_completed(before, after):
                        _stop_process_group(process)
                        return _invoke(
                            arguments,
                            environment,
                            directory,
                            suffix="authenticated-resume",
                            terminal_stdin=False,
                        )
                    next_probe = now + poll_seconds
                time.sleep(min(poll_seconds, 0.1))
            returncode = process.wait()
            after = _credential_snapshot(
                arguments[0],
                authentication["adapter_id"],
                authentication["env_var"],
                environment,
            )
            contract_error = _credential_contract_error(
                after,
                authentication["adapter_id"],
                authentication["env_var"],
            )
            if contract_error is not None:
                raise CommandError(contract_error)
            if _credential_completed(before, after) and returncode != 0:
                return _invoke(
                    arguments,
                    environment,
                    directory,
                    suffix="authenticated-resume",
                    terminal_stdin=False,
                )
            if returncode == 0 and not _credential_completed(before, after):
                raise CommandError(
                    "Play run exited after browser authentication, but the exact "
                    f"credential {authentication['env_var']} was not confirmed healthy."
                )
            return subprocess.CompletedProcess(list(arguments), returncode), stdout_path, stderr_path
    finally:
        if process is not None and process.poll() is None:
            _stop_process_group(process)
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)


def _positive_duration(
    environment: Mapping[str, str], name: str, default: float
) -> float:
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise CommandError(f"{name} must be a number") from error
    if value <= 0:
        raise CommandError(f"{name} must be greater than zero")
    return value


def _stop_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        process.kill()
    process.wait(timeout=2)


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


def _bounded_edge_text(value: bytes | None, path: Path, limit: int) -> str:
    """Preserve both the command preamble and the terminal failure diagnostic."""

    if value is None:
        size = path.stat().st_size
        if size <= limit:
            value = path.read_bytes()
        else:
            head_size = limit // 3
            tail_size = limit - head_size
            with path.open("rb") as handle:
                head = handle.read(head_size)
                handle.seek(-tail_size, os.SEEK_END)
                tail = handle.read(tail_size)
            value = head + b"\n... output omitted ...\n" + tail
    elif len(value) > limit:
        head_size = limit // 3
        tail_size = limit - head_size
        value = value[:head_size] + b"\n... output omitted ...\n" + value[-tail_size:]
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
_LOGIN_MARKERS = ("not logged in", "rote login", "requires login")


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
        rote_command = shutil.which("rote")
        if rote_command is not None:
            return {
                "schema": "play.run-result/v1",
                "ok": False,
                "event": "play_registry_login_required",
                "authentication": {
                    "source": "rote_registry_login_required",
                    "recoverable": True,
                    "evidence_refs": [f"sha256:{digest}"],
                },
                "onboarding": {"rote_command": rote_command},
            }
    return {
        "schema": "play.run-result/v1",
        "ok": False,
        "event": "action_blocked",
        "reason": bounded,
        "recoverable": True,
        "owner": "play",
        "evidence_refs": [f"sha256:{digest}"],
    }


def _authentication_required(
    authentication: Mapping[str, str], reason: str
) -> dict[str, Any]:
    """Offer guided authentication without accepting credentials in the harness."""

    digest = hashlib.sha256(reason.encode()).hexdigest()
    return {
        "schema": "play.run-result/v1",
        "ok": False,
        "event": "play_authentication_required",
        "authentication": {
            "source": "rote_authentication_required",
            "owner": "rote-adapter-config",
            "recoverable": True,
            **dict(authentication),
            "evidence_refs": [f"sha256:{digest}"],
        },
    }


def _declares_auth_ensure(operations: Sequence[object]) -> bool:
    return any(
        isinstance(operation, Mapping)
        and operation.get("operation") == "adapter.auth.ensure"
        for operation in operations
    )


def _typed_auth_failure(output: str) -> dict[str, str] | None:
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

    rendered_source = _rendered_auth_failure(output)
    if rendered_source is not None:
        sources.append(rendered_source)

    # Multiple typed failures in one invocation are ambiguous. Refuse to guess
    # which adapter or credential should be authenticated.
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

    return {
        "adapter_id": adapter_id.strip(),
        "env_var": env_var.strip(),
        "classified_rung": classified_rung,
        "distinguishing_error": f"{state}: {remediation.strip()}",
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
    "Authentication interaction": "authentication_interaction",
    # Backward-compatible input for Rote versions released before the
    # authentication vocabulary became canonical. This label is accepted but
    # never emitted by Play.
    "Repair interaction": "authentication_interaction",
    "Network required": "network_required",
    "Remediation": "remediation",
    "Adapter calls started": "adapter_calls_started",
}


def _auth_protocol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _AUTH_PROTOCOLS.get(value.strip())


def _rendered_auth_failure(output: str) -> Mapping[str, Any] | None:
    """Project Rote's documented authentication rendering onto its v1 wire.

    Rote supports both marker and prose shells at this boundary. Only their
    exact documented fields are accepted, and the adapter-call safety bit must
    be present so ordinary Play output cannot be mistaken for a pre-execution
    authentication refusal.
    """

    lines = output.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if line.strip() in {"@@authentication", "Authentication required"}
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
        if set(fields) == set(_AUTH_MARKER_FIELDS.values()):
            break
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
