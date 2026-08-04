"""Resolve Play machine states into portable orb presentation payloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


SCHEMA = "play.presentation/v1"
ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = ROOT / "references" / "integration" / "thinking-orbs.json"


class PresentationError(RuntimeError):
    pass


def load_mapping() -> dict[str, object]:
    try:
        return json.loads(MAPPING_PATH.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PresentationError(f"cannot load {MAPPING_PATH}: {error}") from error


def resolve(state: str, *, size: int = 20, theme: str = "auto") -> dict[str, object]:
    mapping = load_mapping()
    states = mapping.get("states", {})
    if state not in states:
        raise PresentationError(f"unknown Play machine state: {state}")
    specification = states[state]
    orb = specification["orb"]
    trajectory = mapping["trajectories"][orb]
    message = specification.get("message", trajectory["message"])
    return {
        "schema": SCHEMA,
        "state": state,
        "orb": {"state": orb, "size": size, "theme": theme},
        "message": message,
        "aria_label": specification["label"],
        "terminal": bool(specification.get("terminal", False)),
        "fallback": f"{trajectory['glyph']} {message}",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state")
    parser.add_argument("--size", type=int, choices=(20, 64), default=20)
    parser.add_argument("--theme", choices=("auto", "dark", "light"), default="auto")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = resolve(args.state, size=args.size, theme=args.theme)
    except PresentationError as error:
        parser.exit(2, f"play-presentation: {error}\n")
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else payload["fallback"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
