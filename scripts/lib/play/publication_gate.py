"""Verify public Play adapter contracts and smoke-test the canonical URI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .commands import CommandError, run_rote_json
from .render import json_text


SCHEMA = "play.publication-gate/v1"
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_MISSING_CREDENTIAL = re.compile(
    r"(?:credential|environment variable) [`']?([A-Z][A-Z0-9_]*)[`']?.{0,80}(?:missing|not set)",
    re.IGNORECASE,
)


class PublicationGateError(RuntimeError):
    """A public publication cannot safely be presented yet."""


JsonLoader = Callable[[str], dict[str, Any]]
SmokeRunner = Callable[[Sequence[str], Path], tuple[int, str, str]]


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublicationGateError(f"{label} is missing or malformed")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicationGateError(f"{label} is missing or malformed")
    return value


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _unwrap_play_inspection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        raise PublicationGateError("canonical Play inspection failed")
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("play_inspect"), dict):
        return data["play_inspect"]
    if isinstance(payload.get("play_inspect"), dict):
        return payload["play_inspect"]
    return payload


def _unwrap_local_adapter(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        raise PublicationGateError("installed adapter inspection failed")
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    if isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def _unwrap_registry_adapter(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict) and "adapter" in data and "version" in data:
        return data
    return payload


def _auth_family(kind: object, env_names: Sequence[str]) -> str:
    if env_names:
        return "static"
    normalized = str(kind or "").lower().replace("-", "_")
    if normalized in {"oauth", "oauth2", "oauth_dcr", "dcr", "dynamic_client_registration"}:
        return "oauth"
    if normalized in {"none", "no_auth", "anonymous"}:
        return "none"
    if normalized in {"bearer", "basic", "api_key", "apikey", "token", "header"}:
        return "static"
    return "unknown"


def _published_env_names(auth: Mapping[str, Any]) -> list[str]:
    names: set[str] = set()
    for key, value in auth.items():
        if key.endswith("_env") and isinstance(value, str) and _ENV_NAME.fullmatch(value):
            names.add(value)
        elif key.endswith("_envs") and isinstance(value, list):
            names.update(
                item for item in value if isinstance(item, str) and _ENV_NAME.fullmatch(item)
            )
    return sorted(names)


def _local_auth(local: Mapping[str, Any]) -> tuple[str, list[str]]:
    authentication = local.get("authentication")
    if not isinstance(authentication, dict):
        return "unknown", []
    names: set[str] = set()
    kinds: list[str] = []
    if isinstance(authentication.get("kind"), str):
        kinds.append(authentication["kind"])
    bindings = authentication.get("bindings")
    if isinstance(bindings, list):
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            credential = binding.get("credential")
            if isinstance(credential, str) and _ENV_NAME.fullmatch(credential):
                names.add(credential)
            if isinstance(binding.get("kind"), str):
                kinds.append(binding["kind"])
    return (kinds[0] if kinds else "unknown"), sorted(names)


def _expected_identity(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    publication = _object(payload.get("publication"), "publication")
    play = _object(payload.get("play"), "play")
    if publication.get("visibility") != "public":
        raise PublicationGateError("publication gate applies only to public Plays")
    version = _string(play.get("version"), "play.version")
    return publication, play, version


def validate_credential_contracts(
    payload: Mapping[str, Any],
    play_inspection: dict[str, Any],
    local_loader: JsonLoader,
    registry_loader: JsonLoader,
) -> dict[str, Any]:
    """Compare associated adapter metadata without reading credential values."""

    started = time.perf_counter_ns()
    publication, _, version = _expected_identity(payload)
    inspected = _unwrap_play_inspection(play_inspection)
    identity = _object(inspected.get("identity"), "inspected identity")
    canonical = _string(publication.get("canonical_reference"), "publication.canonical_reference")
    expected_owner, separator, expected_name = canonical.partition("/")
    expected_name = expected_name.split("@", 1)[0]
    if not separator or not expected_owner or not expected_name:
        raise PublicationGateError("publication.canonical_reference must be owner/name")
    expected_identity = (expected_owner, expected_name, version, "public")
    actual_identity = (
        identity.get("owner"),
        identity.get("name"),
        identity.get("version"),
        identity.get("visibility"),
    )
    if actual_identity != expected_identity:
        raise PublicationGateError("canonical Play identity does not match the publication")

    execution = _object(inspected.get("execution"), "Play execution contract")
    if execution.get("play_run_eligible") is not True or execution.get("blockers"):
        raise PublicationGateError("canonical Play is not run-eligible")
    convergence = _object(inspected.get("convergence"), "Play convergence contract")
    raw_adapters = convergence.get("adapters")
    if not isinstance(raw_adapters, list):
        raise PublicationGateError("Play convergence lacks associated adapter checks")

    contracts: list[dict[str, Any]] = []
    for raw in raw_adapters:
        adapter = _object(raw, "associated adapter check")
        adapter_id = _string(adapter.get("adapter_id"), "associated adapter id")
        selected_source = _string(
            adapter.get("selected_candidate"), f"{adapter_id} selected adapter source"
        )
        candidates = _strings(adapter.get("registry_candidates"))
        if selected_source not in candidates:
            raise PublicationGateError(
                f"adapter {adapter_id} selected source is absent from registry candidates"
            )
        if adapter.get("local_state") != "receipt_verified" or adapter.get("decision") != "ready":
            raise PublicationGateError(
                f"adapter {adapter_id} does not have ready, receipt-verified provenance"
            )

        demand = _object(adapter.get("credential_demand"), f"{adapter_id} credential demand")
        demanded_names = _strings(demand.get("names"))
        demand_protocols = _strings(demand.get("protocols"))

        local = _unwrap_local_adapter(local_loader(adapter_id))
        local_identity = _object(local.get("identity"), f"{adapter_id} local identity")
        local_source = _object(local.get("source"), f"{adapter_id} local source")
        local_kind, local_names = _local_auth(local)

        published = _unwrap_registry_adapter(registry_loader(selected_source))
        registry_adapter = _object(published.get("adapter"), f"{selected_source} registry identity")
        registry_version = _object(published.get("version"), f"{selected_source} registry version")
        manifest = _object(registry_version.get("manifest"), f"{selected_source} manifest")
        published_auth = manifest.get("auth")
        if published_auth is None:
            published_auth = {"type": "none"}
        published_auth = _object(published_auth, f"{selected_source} auth contract")
        published_names = _published_env_names(published_auth)
        published_kind = published_auth.get("type") or published_auth.get("kind")

        local_fingerprint = _string(local_source.get("fingerprint"), f"{adapter_id} fingerprint")
        registry_fingerprint = _string(
            registry_adapter.get("fingerprint"), f"{selected_source} fingerprint"
        )
        local_version = _string(local_identity.get("version"), f"{adapter_id} local version")
        selected_version = _string(
            registry_version.get("version"), f"{selected_source} selected version"
        )
        if local_fingerprint != registry_fingerprint:
            raise PublicationGateError(
                f"adapter {adapter_id} fingerprint differs from {selected_source}"
            )
        if local_version != selected_version:
            raise PublicationGateError(
                f"adapter {adapter_id} version differs from {selected_source}"
            )

        published_family = _auth_family(published_kind, published_names)
        local_family = _auth_family(local_kind, local_names)
        demanded_families = sorted(
            {_auth_family(protocol, []) for protocol in demand_protocols} - {"unknown"}
        )
        if published_family == "unknown" or local_family == "unknown":
            raise PublicationGateError(f"adapter {adapter_id} auth family is not comparable")
        if published_family != local_family:
            raise PublicationGateError(
                f"adapter {adapter_id} local auth family differs from {selected_source}"
            )
        if demanded_families and published_family not in demanded_families:
            raise PublicationGateError(
                f"adapter {adapter_id} resolved credential protocol differs from {selected_source}"
            )
        if published_names or local_names or demanded_names:
            if not published_names or published_names != local_names or published_names != demanded_names:
                raise PublicationGateError(
                    f"adapter {adapter_id} credential environment-variable contract differs from {selected_source}"
                )

        contracts.append(
            {
                "adapter_id": adapter_id,
                "selected_source": selected_source,
                "selected_version": selected_version,
                "fingerprint": registry_fingerprint,
                "auth_family": published_family,
                "credential_names": published_names,
                "credential_status": demand.get("status") or "unknown",
                "provenance": "receipt_verified",
            }
        )

    canonical_contracts = json.dumps(contracts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical_contracts.encode()).hexdigest()
    return {
        "schema": SCHEMA,
        "kind": "credential_contracts",
        "ok": True,
        "credential_status": "verified",
        "adapter_contracts": contracts,
        "credential_contract_sha256": digest,
        "credential_check_ns": time.perf_counter_ns() - started,
        "evidence_refs": [f"sha256:{digest}"],
    }


def _default_local_loader(adapter_id: str) -> dict[str, Any]:
    return _object(
        run_rote_json("adapter", "info", adapter_id, "--json", error_type=CommandError),
        f"{adapter_id} local adapter response",
    )


def _default_registry_loader(source: str) -> dict[str, Any]:
    return _object(
        run_rote_json(
            "registry", "adapter", "info", source, "--json", error_type=CommandError
        ),
        f"{source} registry adapter response",
    )


def inspect_publication_credentials(payload: Mapping[str, Any]) -> dict[str, Any]:
    publication, _, _ = _expected_identity(payload)
    uri = _string(publication.get("uri"), "publication.uri")
    inspected = _object(
        run_rote_json("play", "inspect", uri, "--json", error_type=CommandError),
        "canonical Play inspection response",
    )
    return validate_credential_contracts(
        payload, inspected, _default_local_loader, _default_registry_loader
    )


def _default_smoke_runner(command: Sequence[str], working_directory: Path) -> tuple[int, str, str]:
    environment = os.environ.copy()
    environment.setdefault("ROTE_NO_HINTS", "1")
    environment.setdefault("ROTE_FLOW_PROGRESS", "0")
    raw_timeout = environment.get("PLAY_PUBLIC_SMOKE_TIMEOUT_SECONDS", "120")
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as error:
        raise PublicationGateError("PLAY_PUBLIC_SMOKE_TIMEOUT_SECONDS must be a number") from error
    if timeout_seconds <= 0:
        raise PublicationGateError("public smoke timeout must be greater than zero")
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            env=environment,
            cwd=working_directory,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise PublicationGateError(
            f"canonical public Play run timed out after {timeout_seconds:g}s"
        ) from error
    return completed.returncode, completed.stdout, completed.stderr


def _parameters(payload: Mapping[str, Any]) -> list[str]:
    request = payload.get("request")
    if not isinstance(request, Mapping):
        return []
    raw = request.get("parameters")
    if not isinstance(raw, Mapping):
        return []
    parameters = []
    for key in sorted(raw):
        if not isinstance(key, str) or not key or "=" in key:
            raise PublicationGateError("public smoke parameter names must be non-empty strings")
        value = raw[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = "null"
        elif isinstance(value, (str, int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
        parameters.append(f"{key}={rendered}")
    return parameters


def _failure_class(detail: str) -> tuple[str, list[str]]:
    match = _MISSING_CREDENTIAL.search(detail)
    if match:
        return "credential_missing", [match.group(1).upper()]
    lowered = detail.lower()
    if "provenance" in lowered or "receipt" in lowered or "adapter" in lowered:
        return "adapter_resolution", []
    return "execution_failed", []


def smoke_publication(
    payload: Mapping[str, Any], runner: SmokeRunner = _default_smoke_runner
) -> dict[str, Any]:
    """Run the exact public URI once without retaining its primary output."""

    started = time.perf_counter_ns()
    publication, _, version = _expected_identity(payload)
    uri = _string(publication.get("uri"), "publication.uri")
    if f"@{version}" not in uri:
        raise PublicationGateError("publication.uri must identify the exact published version")
    command = ["rote", "play", "run", uri, *_parameters(payload), "--yes"]
    temp_parent = Path("/tmp") if Path("/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="play-public-smoke-", dir=temp_parent) as directory:
        returncode, stdout, stderr = runner(command, Path(directory))
    detail = stderr.strip() or stdout.strip()
    output_digest = hashlib.sha256(stdout.encode()).hexdigest()
    elapsed = time.perf_counter_ns() - started
    if returncode:
        failure_class, credential_names = _failure_class(detail)
        failure_digest = hashlib.sha256(detail.encode()).hexdigest()
        return {
            "schema": SCHEMA,
            "kind": "public_smoke",
            "ok": False,
            "smoke_status": "failed",
            "failure_class": failure_class,
            "reason": (
                "canonical public Play run could not resolve its declared credential"
                if failure_class == "credential_missing"
                else "canonical public Play run failed"
            ),
            "credential_names": credential_names,
            "failure_ref": f"sha256:{failure_digest}",
            "evidence_refs": [f"sha256:{failure_digest}"],
            "smoke_ns": elapsed,
            "isolated_workdir": True,
        }
    return {
        "schema": SCHEMA,
        "kind": "public_smoke",
        "ok": True,
        "smoke_status": "verified",
        "smoke_exact_reference": uri,
        "smoke_run_ref": f"sha256:{output_digest}",
        "smoke_output_sha256": output_digest,
        "smoke_output_bytes": len(stdout.encode()),
        "smoke_ns": elapsed,
        "isolated_workdir": True,
    }


def _read_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise PublicationGateError("stdin must contain valid JSON") from error
    return _object(payload, "publication gate input")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("credentials", "smoke"))
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if not args.stdin:
        parser.error("--stdin is required")
    try:
        payload = _read_payload()
        result = (
            inspect_publication_credentials(payload)
            if args.mode == "credentials"
            else smoke_publication(payload)
        )
    except CommandError as error:
        failure_digest = hashlib.sha256(str(error).encode()).hexdigest()
        result = {
            "schema": SCHEMA,
            "kind": args.mode,
            "ok": False,
            "failure_class": "metadata_read_failed",
            "reason": "Rote metadata inspection failed",
            "credential_names": [],
            "evidence_refs": [f"sha256:{failure_digest}"],
        }
    except PublicationGateError as error:
        failure_digest = hashlib.sha256(str(error).encode()).hexdigest()
        result = {
            "schema": SCHEMA,
            "kind": args.mode,
            "ok": False,
            "failure_class": "contract_check_failed",
            "reason": str(error),
            "credential_names": [],
            "evidence_refs": [f"sha256:{failure_digest}"],
        }
    print(json_text(result) if args.as_json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
