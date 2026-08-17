"""Validated user and project routing policy for Play's prompt interceptor."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .state_home import state_path


SCHEMA = "play.routing/v1"
PROJECT_POLICY = Path(".play") / "routing.yaml"
STRATEGIES = ("direct",)
EXECUTORS = ("api", "cli")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class RoutingError(ValueError):
    """The routing policy or requested policy mutation is invalid."""


def empty_policy() -> dict[str, Any]:
    return {"schema": SCHEMA, "routes": []}


def user_policy_path() -> Path:
    override = os.environ.get("PLAY_ROUTING_USER_PATH")
    return Path(override).expanduser() if override else state_path("routing.yaml")


def project_policy_path(project: str | Path | None = None) -> Path:
    root = Path(project) if project is not None else Path.cwd()
    return root.expanduser().resolve() / PROJECT_POLICY


def find_project_policy(project: str | Path | None) -> Path | None:
    if project is None:
        return None
    current = Path(project).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate_root in (current, *current.parents):
        candidate = candidate_root / PROJECT_POLICY
        if candidate.is_file():
            return candidate
        if (candidate_root / ".git").exists():
            break
    return None


def load_policy(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if missing_ok:
            return empty_policy()
        raise RoutingError(f"routing policy does not exist: {path}") from None
    except (OSError, yaml.YAMLError) as error:
        raise RoutingError(f"cannot read routing policy {path}: {error}") from error
    return validate_policy(raw, source=path)


def validate_policy(raw: object, *, source: Path | None = None) -> dict[str, Any]:
    label = str(source) if source is not None else "routing policy"
    if not isinstance(raw, Mapping):
        raise RoutingError(f"{label}: root must be an object")
    if set(raw) != {"schema", "routes"}:
        raise RoutingError(f"{label}: only schema and routes are allowed")
    if raw.get("schema") != SCHEMA:
        raise RoutingError(f"{label}: schema must be {SCHEMA}")
    routes = raw.get("routes")
    if not isinstance(routes, list):
        raise RoutingError(f"{label}: routes must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, route in enumerate(routes):
        if not isinstance(route, Mapping):
            raise RoutingError(f"{label}: routes[{index}] must be an object")
        if set(route) != {"id", "strategy", "providers", "tools", "executors"}:
            raise RoutingError(
                f"{label}: routes[{index}] must declare exactly id, strategy, providers, tools, and executors"
            )
        route_id = route.get("id")
        if not isinstance(route_id, str) or not _IDENTIFIER.fullmatch(route_id):
            raise RoutingError(f"{label}: routes[{index}].id is invalid")
        if route_id in seen:
            raise RoutingError(f"{label}: duplicate route id {route_id}")
        seen.add(route_id)
        strategy = route.get("strategy")
        if strategy not in STRATEGIES:
            raise RoutingError(f"{label}: routes[{index}].strategy must be direct")
        providers = _string_list(route.get("providers"), f"{label}: routes[{index}].providers")
        tools = _string_list(route.get("tools"), f"{label}: routes[{index}].tools")
        executors = _string_list(route.get("executors"), f"{label}: routes[{index}].executors")
        if not providers and not tools:
            raise RoutingError(f"{label}: routes[{index}] needs a provider or tool")
        if not executors or any(item not in EXECUTORS for item in executors):
            raise RoutingError(f"{label}: routes[{index}].executors must use api and/or cli")
        normalized.append(
            {
                "id": route_id,
                "strategy": strategy,
                "providers": providers,
                "tools": tools,
                "executors": executors,
            }
        )
    return {"schema": SCHEMA, "routes": normalized}


def initialize(path: Path, *, private: bool = False) -> bool:
    if path.exists():
        return False
    _write_policy(path, empty_policy(), private=private)
    return True


def add_route(
    path: Path,
    *,
    route_id: str,
    providers: Sequence[str] = (),
    tools: Sequence[str] = (),
    executors: Sequence[str] = EXECUTORS,
    private: bool = False,
) -> str:
    policy = load_policy(path, missing_ok=True)
    route = validate_policy(
        {
            "schema": SCHEMA,
            "routes": [
                {
                    "id": route_id,
                    "strategy": "direct",
                    "providers": list(providers),
                    "tools": list(tools),
                    "executors": list(executors),
                }
            ],
        }
    )["routes"][0]
    routes = policy["routes"]
    existing = next(
        (index for index, item in enumerate(routes) if item["id"] == route_id),
        None,
    )
    status = "updated" if existing is not None else "added"
    if existing is None:
        routes.append(route)
    else:
        routes[existing] = route
    _write_policy(path, policy, private=private)
    return status


def remove_route(path: Path, route_id: str, *, private: bool = False) -> None:
    policy = load_policy(path)
    remaining = [route for route in policy["routes"] if route["id"] != route_id]
    if len(remaining) == len(policy["routes"]):
        raise RoutingError(f"routing policy has no route named {route_id}")
    policy["routes"] = remaining
    _write_policy(path, policy, private=private)


def active_routes(project_path: str | Path | None = None) -> list[dict[str, Any]]:
    paths = [user_policy_path()]
    project = find_project_policy(project_path)
    if project is not None:
        paths.append(project)
    routes: list[dict[str, Any]] = []
    for path in paths:
        try:
            routes.extend(load_policy(path, missing_ok=True)["routes"])
        except RoutingError:
            # A malformed policy can never authorize a direct route. The normal
            # Play activation path remains available and the CLI exposes errors.
            continue
    return routes


def matching_direct_route(
    prompt: str, *, project_path: str | Path | None = None
) -> dict[str, Any] | None:
    normalized = _normalized_text(prompt)
    for route in active_routes(project_path):
        selectors = [*route["providers"], *route["tools"]]
        if any(_selector_matches(normalized, selector) for selector in selectors):
            return route
    return None


def _normalized_text(value: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() + " "


def _selector_matches(normalized_prompt: str, selector: str) -> bool:
    normalized_selector = _normalized_text(selector).strip()
    return bool(normalized_selector) and f" {normalized_selector} " in normalized_prompt


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in value
    ):
        raise RoutingError(f"{label} must be a list of lowercase identifiers")
    return list(dict.fromkeys(value))


def _write_policy(path: Path, policy: Mapping[str, Any], *, private: bool) -> None:
    validated = validate_policy(policy, source=path)
    mode = 0o600 if private else 0o644
    directory_mode = 0o700 if private else 0o755
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=directory_mode)
        if private:
            path.parent.chmod(directory_mode)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(validated, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        path.chmod(mode)
    except OSError as error:
        raise RoutingError(f"cannot write routing policy {path}: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _policy_target(user: bool, project: str | None) -> tuple[Path, bool]:
    if user and project is not None:
        raise RoutingError("choose either --user or --project")
    return (user_policy_path(), True) if user else (project_policy_path(project), False)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-routing", description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--user", action="store_true", help="manage the owner-private user policy")
    target.add_argument("--project", help="manage <project>/.play/routing.yaml (default: cwd)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create an empty policy without replacing an existing one")
    add = commands.add_parser("add", help="add or replace one direct route")
    add.add_argument("route_id")
    add.add_argument("--provider", action="append", default=[])
    add.add_argument("--tool", action="append", default=[])
    add.add_argument("--executor", action="append", choices=EXECUTORS, default=[])
    remove = commands.add_parser("remove", help="remove one route by id")
    remove.add_argument("route_id")
    listing = commands.add_parser("list", help="show the selected policy")
    listing.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        path, private = _policy_target(args.user, args.project)
        if args.command == "init":
            status = "created" if initialize(path, private=private) else "current"
            print(f"{status}: {path}")
        elif args.command == "add":
            executors = args.executor or list(EXECUTORS)
            status = add_route(
                path,
                route_id=args.route_id,
                providers=args.provider,
                tools=args.tool,
                executors=executors,
                private=private,
            )
            print(f"{status} {args.route_id}: {path}")
        elif args.command == "remove":
            remove_route(path, args.route_id, private=private)
            print(f"removed {args.route_id}: {path}")
        else:
            policy = load_policy(path)
            if args.json:
                print(json.dumps(policy, indent=2, sort_keys=True))
            else:
                print(yaml.safe_dump(policy, sort_keys=False), end="")
    except RoutingError as error:
        parser.exit(1, f"play-routing: {error}\n")
    return 0
