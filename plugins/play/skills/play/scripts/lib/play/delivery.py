"""Two-phase, host-neutral delivery contract for scheduled Play digests."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .digest import collect_digest, render_markdown
from .registry import RegistryReadError
from .render import json_text
from .timewindow import CHECKPOINT_SCHEMA, TimeWindowError


DELIVERY_SCHEMA = "play.digest-delivery/v1"
ACK_SCHEMA = "play.digest-delivery-ack/v1"


class DeliveryError(ValueError):
    """A delivery envelope or acknowledgment violates the contract."""


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _delivery_id(digest: dict[str, Any], target: dict[str, str]) -> str:
    identity = {
        "target_key": target["key"],
        "channel": target["channel"],
        "window": digest.get("window"),
        "digest": digest,
    }
    return "pd_" + hashlib.sha256(_canonical_json(identity).encode()).hexdigest()[:24]


def build_delivery(
    digest: dict[str, Any],
    *,
    target_key: str,
    channel: str,
) -> dict[str, Any]:
    """Wrap an immutable digest in an idempotent host-delivery envelope."""

    if digest.get("schema") != "play.digest/v1" or digest.get("complete") is not True:
        raise DeliveryError("delivery requires a complete play.digest/v1 payload")
    if not target_key.strip():
        raise DeliveryError("target_key must be a non-empty opaque host identifier")
    if not channel.strip():
        raise DeliveryError("channel must be non-empty")
    checkpoint = digest.get("next_checkpoint")
    if not isinstance(checkpoint, dict) or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise DeliveryError(f"digest next_checkpoint must use {CHECKPOINT_SCHEMA}")

    target = {"key": target_key, "channel": channel}
    delivery_id = _delivery_id(digest, target)
    updates = digest.get("org_updates", {})
    new_count = len(updates.get("new", []))
    revised_count = len(updates.get("revised", []))
    return {
        "schema": DELIVERY_SCHEMA,
        "delivery_id": delivery_id,
        "target": target,
        "status": "ready",
        "summary": {
            "new_count": new_count,
            "revised_count": revised_count,
            "public_count": len(digest.get("public_top", [])),
            "has_updates": bool(new_count or revised_count),
        },
        "message": {
            "content_type": "text/markdown",
            "body": render_markdown(digest),
        },
        "digest": digest,
        "checkpoint_release": {
            "policy": "after_matching_delivered_ack",
            "candidate": checkpoint,
        },
    }


def release_checkpoint(envelope: dict[str, Any], ack: dict[str, Any]) -> dict[str, str]:
    """Return the proposed checkpoint only after validating a matching success ack."""

    if envelope.get("schema") != DELIVERY_SCHEMA:
        raise DeliveryError(f"envelope must use {DELIVERY_SCHEMA}")
    if ack.get("schema") != ACK_SCHEMA:
        raise DeliveryError(f"acknowledgment must use {ACK_SCHEMA}")
    target = envelope.get("target")
    digest = envelope.get("digest")
    if (
        not isinstance(target, dict)
        or not isinstance(target.get("key"), str)
        or not isinstance(target.get("channel"), str)
        or not isinstance(digest, dict)
    ):
        raise DeliveryError("envelope target or digest is malformed")
    delivery_id = envelope.get("delivery_id")
    if delivery_id != _delivery_id(digest, target):
        raise DeliveryError("envelope delivery_id does not match its contents")
    if not isinstance(delivery_id, str) or ack.get("delivery_id") != delivery_id:
        raise DeliveryError("acknowledgment delivery_id does not match the envelope")
    if ack.get("status") != "delivered":
        raise DeliveryError("checkpoint release requires acknowledgment status delivered")
    release = envelope.get("checkpoint_release")
    checkpoint = release.get("candidate") if isinstance(release, dict) else None
    if not isinstance(checkpoint, dict) or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise DeliveryError(f"envelope checkpoint must use {CHECKPOINT_SCHEMA}")
    if checkpoint != digest.get("next_checkpoint"):
        raise DeliveryError("envelope checkpoint does not match the digest")
    last_seen_at = checkpoint.get("last_seen_at")
    if not isinstance(last_seen_at, str) or not last_seen_at:
        raise DeliveryError("envelope checkpoint is missing last_seen_at")
    return {"schema": CHECKPOINT_SCHEMA, "last_seen_at": last_seen_at}


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise DeliveryError(f"cannot load {label}: {error}") from error
    if not isinstance(payload, dict):
        raise DeliveryError(f"{label} must be a JSON object")
    return payload


def _prepare_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("prepare", help="prepare an immutable delivery envelope")
    parser.add_argument("--target-key", required=True, help="opaque host-owned destination key")
    parser.add_argument("--channel", default="harness", help="host delivery channel label")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--since", help="ISO-8601 start timestamp supplied by the host")
    parser.add_argument("--checkpoint", type=Path, help="read a host-persisted checkpoint token")
    parser.add_argument("--public-limit", type=int, default=10)
    parser.add_argument("--inspection-budget", type=int, default=100)
    parser.add_argument("--update-metadata-budget", type=int, default=100)
    parser.add_argument("--update-inspection-budget", type=int, default=4)
    parser.add_argument("--org", action="append", default=[])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    _prepare_parser(subparsers)
    release = subparsers.add_parser(
        "release", help="validate delivery success and emit the checkpoint to persist"
    )
    release.add_argument("--envelope", type=Path, required=True)
    release.add_argument("--ack", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.action == "prepare":
            digest = collect_digest(
                days=args.days,
                since=args.since,
                checkpoint=args.checkpoint,
                public_limit=args.public_limit,
                inspection_budget=args.inspection_budget,
                update_metadata_budget=args.update_metadata_budget,
                update_inspection_budget=args.update_inspection_budget,
                org_slugs=args.org,
            )
            output = build_delivery(
                digest,
                target_key=args.target_key,
                channel=args.channel,
            )
        else:
            output = release_checkpoint(
                _load_object(args.envelope, label="envelope"),
                _load_object(args.ack, label="acknowledgment"),
            )
    except (DeliveryError, RegistryReadError, TimeWindowError, ValueError) as error:
        print(f"play-delivery: {error}", file=sys.stderr)
        return 1
    print(json_text(output))
    return 0
