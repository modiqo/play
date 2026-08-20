"""Model identity, trace I/O, and estimated cost for Journey views.

Rote response envelopes count the request sent to a capability and the response
returned by it.  From the embodied agent's vantage, the response is input and
the request is output.  The resulting model-price estimate is therefore a trace
I/O estimate, not a provider invoice: hidden reasoning and unrecorded dialogue
are deliberately not invented.
"""

from __future__ import annotations

import filecmp
import json
import os
import sqlite3
import tempfile
from functools import lru_cache
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


CONFIG_SCHEMA = "play.model-config/v1"
TELEMETRY_SCHEMA = "play.journey-model-telemetry/v1"
CATALOG_NAME = "model_prices_and_context_window.json"
CONFIG_NAME = "model-config.yaml"
CATALOG_SOURCE = (
    "https://raw.githubusercontent.com/BerriAI/litellm/refs/heads/main/"
    "model_prices_and_context_window.json"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BUNDLED_CONFIG = REPOSITORY_ROOT / "references" / "journey" / CONFIG_NAME
BUNDLED_CATALOG = REPOSITORY_ROOT / "references" / "journey" / CATALOG_NAME


class ModelTelemetryError(RuntimeError):
    """Model telemetry assets or configuration are invalid."""


def play_home(home: Path | None = None) -> Path:
    if home is not None:
        return home.expanduser()
    configured = os.environ.get("PLAY_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".play"


def _atomic_copy(source: Path, target: Path, *, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_model_assets(
    *, source_root: Path | None = None, home: Path | None = None
) -> dict[str, Any]:
    """Install an owner-editable config and refresh the derived price cache."""

    root = source_root.resolve() if source_root is not None else REPOSITORY_ROOT
    bundled_config = root / "references" / "journey" / CONFIG_NAME
    bundled_catalog = root / "references" / "journey" / CATALOG_NAME
    if not bundled_config.is_file() or not bundled_catalog.is_file():
        raise ModelTelemetryError("bundled Journey model assets are missing")
    try:
        config_value = yaml.safe_load(bundled_config.read_text(encoding="utf-8"))
        catalog_value = json.loads(bundled_catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise ModelTelemetryError(f"bundled Journey model assets are invalid: {error}") from error
    if not isinstance(config_value, Mapping) or config_value.get("schema") != CONFIG_SCHEMA:
        raise ModelTelemetryError("bundled Journey model config has the wrong schema")
    if not isinstance(catalog_value, Mapping) or "gpt-5" not in catalog_value:
        raise ModelTelemetryError("bundled LiteLLM catalog is incomplete")

    owner_root = play_home(home)
    owner_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(owner_root, 0o700)
    config_path = owner_root / CONFIG_NAME
    cache_path = owner_root / "cache" / CATALOG_NAME
    config_created = not config_path.exists()
    if config_created:
        _atomic_copy(bundled_config, config_path, mode=0o600)
    catalog_refreshed = not cache_path.is_file() or not filecmp.cmp(
        bundled_catalog, cache_path, shallow=False
    )
    if catalog_refreshed:
        _atomic_copy(bundled_catalog, cache_path, mode=0o600)
    return {
        "config": str(config_path),
        "catalog": str(cache_path),
        "config_created": config_created,
        "catalog_refreshed": catalog_refreshed,
    }


def load_model_config(*, home: Path | None = None) -> dict[str, Any]:
    assets = ensure_model_assets(home=home)
    path = Path(assets["config"])
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ModelTelemetryError(f"cannot read {path}: {error}") from error
    if not isinstance(value, Mapping) or value.get("schema") != CONFIG_SCHEMA:
        raise ModelTelemetryError(f"{path} must use schema {CONFIG_SCHEMA}")
    return dict(value)


def _workspace_model(workspace: Path) -> dict[str, Any] | None:
    database = workspace / ".rote" / "workspace.db"
    if not database.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT value FROM workspace_meta WHERE key = 'exploration_model'"
        ).fetchone()
        if row is None or not isinstance(row[0], str):
            return None
        value = json.loads(row[0])
    except (sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        if connection is not None:
            connection.close()
    return dict(value) if isinstance(value, Mapping) else None


def _string(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _family(model: str) -> str:
    lowered = model.lower()
    if lowered.startswith("gpt-5"):
        return "gpt-5"
    if "codex" in lowered:
        return "codex"
    if lowered.startswith("claude-"):
        parts = lowered.split("-")
        return "-".join(parts[:3]) if len(parts) >= 3 else lowered
    if lowered.startswith("gemini-"):
        return "gemini"
    return lowered.split("/")[-1]


def select_model(workspace: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    configured = config.get("model")
    configured = configured if isinstance(configured, Mapping) else {}
    selection = config.get("selection")
    selection = selection if isinstance(selection, Mapping) else {}
    recorded = _workspace_model(workspace) if selection.get("prefer_workspace_model", True) else None

    provider = _string(recorded.get("provider") if recorded else None, _string(configured.get("provider"), "openai"))
    name = _string(recorded.get("model") if recorded else None, _string(configured.get("name"), "codex"))
    source = "rote_workspace" if recorded else "play_default"
    key = f"{provider}/{name}"
    overrides = config.get("overrides")
    overrides = overrides if isinstance(overrides, Mapping) else {}
    override = overrides.get(key)
    override = override if isinstance(override, Mapping) else {}
    family = _string(override.get("family"), _family(name) if recorded else _string(configured.get("family"), "codex"))
    effort = _string(override.get("effort"), _string(configured.get("effort"), "medium"))
    pricing_model = _string(
        override.get("pricing_model"),
        name if recorded else _string(configured.get("pricing_model"), "gpt-5-codex"),
    )
    return {
        "provider": provider,
        "name": name,
        "family": family,
        "effort": effort,
        "pricing_model": pricing_model,
        "source": source,
        "captured_at": recorded.get("captured_at") if recorded else None,
    }


@lru_cache(maxsize=4)
def _load_catalog_file(path_value: str, modified_ns: int, size: int) -> Mapping[str, Any]:
    del modified_ns, size
    path = Path(path_value)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ModelTelemetryError(f"cached LiteLLM catalog {path} is not an object")
    return value


def load_catalog(config: Mapping[str, Any], *, home: Path | None = None) -> Mapping[str, Any]:
    catalog_config = config.get("catalog")
    catalog_config = catalog_config if isinstance(catalog_config, Mapping) else {}
    relative = _string(catalog_config.get("cache"), f"cache/{CATALOG_NAME}")
    path = play_home(home) / relative
    try:
        stat = path.stat()
        value = _load_catalog_file(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, json.JSONDecodeError) as error:
        raise ModelTelemetryError(f"cannot read cached LiteLLM catalog {path}: {error}") from error
    return value


def pricing_for(model: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any] | None:
    provider = _string(model.get("provider"), "")
    candidates = [
        _string(model.get("pricing_model"), ""),
        f"{provider}/{_string(model.get('name'), '')}",
        _string(model.get("name"), ""),
    ]
    for key in candidates:
        value = catalog.get(key)
        if not isinstance(value, Mapping):
            continue
        catalog_provider = value.get("litellm_provider")
        if isinstance(catalog_provider, str) and provider and catalog_provider != provider:
            continue
        input_rate = value.get("input_cost_per_token")
        output_rate = value.get("output_cost_per_token")
        if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
            continue
        return {
            "key": key,
            "input_cost_per_token": float(input_rate),
            "output_cost_per_token": float(output_rate),
            "currency": "USD",
            "source": CATALOG_SOURCE,
        }
    return None


def interaction_cost(input_tokens: int, output_tokens: int, pricing: Mapping[str, Any] | None) -> float | None:
    if pricing is None:
        return None
    return round(
        input_tokens * float(pricing["input_cost_per_token"])
        + output_tokens * float(pricing["output_cost_per_token"]),
        12,
    )


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    costs = [record.get("estimated_cost_usd") for record in records]
    priced = [float(value) for value in costs if isinstance(value, (int, float))]
    succeeded = sum(record.get("status") == "succeeded" for record in records)
    failed = sum(record.get("status") == "failed" for record in records)
    return {
        "input_tokens": sum(int(record.get("input_tokens") or 0) for record in records),
        "output_tokens": sum(int(record.get("output_tokens") or 0) for record in records),
        "cost_usd": round(sum(priced), 12) if len(priced) == len(records) else None,
        "count": len(records),
        "success": succeeded,
        "error": failed,
    }


def telemetry_context(workspace: Path, records: list[dict[str, Any]], *, home: Path | None = None) -> dict[str, Any]:
    config = load_model_config(home=home)
    model = select_model(workspace, config)
    pricing = pricing_for(model, load_catalog(config, home=home))
    for record in records:
        record["estimated_cost_usd"] = interaction_cost(
            int(record.get("input_tokens") or 0),
            int(record.get("output_tokens") or 0),
            pricing,
        )
    return {
        "schema": TELEMETRY_SCHEMA,
        "model": model,
        "pricing": pricing,
        "scope": "captured_tool_io",
        "cost_kind": "estimated_lower_bound",
        "session": summarize(records),
    }
