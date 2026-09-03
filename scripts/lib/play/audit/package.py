"""Load everything an installed Play package carries, without executing any of it."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frontmatter as fm

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover - exercised only on 3.10 hosts
    _toml = None  # type: ignore[assignment]


@dataclass
class Tool:
    command: str
    required: bool
    version_requirement: str | None
    install_hint: str | None


@dataclass
class Package:
    root: Path
    reference: str
    version: str | None
    source: str
    frontmatter: fm.Frontmatter
    tools: dict[str, Tool] = field(default_factory=dict)
    deps_present: bool = False
    deps_error: str | None = None
    manifest: dict[str, Any] | None = None
    manifest_error: str | None = None
    resources: dict[str, Path] = field(default_factory=dict)
    python_resources: list[Path] = field(default_factory=list)
    shell_resources: list[Path] = field(default_factory=list)
    script_resources: list[Path] = field(default_factory=list)  # .js .mjs .cjs .ts
    digest: str = ""

    @property
    def main_path(self) -> Path:
        return self.root / "main.ts"

    def has_resource(self, relative: str) -> bool:
        return relative.strip("/") in self.resources

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def _reference_for(root: Path) -> tuple[str, str | None]:
    """``owner/name`` from the install layout ``<flows>/<owner>/<name>``."""
    owner = root.parent.name if root.parent.name else "local"
    name = root.name
    return f"{owner}/{name}", None


def _install_receipt_digest(root: Path) -> str | None:
    receipt = root / ".rote-install-receipt.json"
    if not receipt.is_file():
        return None
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    digest = payload.get("digest") if isinstance(payload, dict) else None
    return digest if isinstance(digest, str) else None


def _content_digest(root: Path) -> str:
    """Stable digest over shipped files so history keys on package content."""
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].startswith("."):
            continue
        hasher.update(str(relative).encode())
        hasher.update(b"\0")
        try:
            hasher.update(path.read_bytes())
        except OSError:
            hasher.update(b"<unreadable>")
        hasher.update(b"\0")
    return "sha256:" + hasher.hexdigest()


def _load_tools(root: Path) -> tuple[dict[str, Tool], bool, str | None]:
    deps = root / "deps.toml"
    if not deps.is_file():
        return {}, False, None
    if _toml is None:
        return {}, True, "deps.toml could not be read: tomllib needs Python 3.11 or newer"
    try:
        data = _toml.loads(deps.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {}, True, f"deps.toml could not be parsed: {error}"
    tools: dict[str, Tool] = {}
    for entry in data.get("tools", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        command = entry.get("command") or entry.get("id")
        if not isinstance(command, str):
            continue
        hint = None
        installs = entry.get("install")
        if isinstance(installs, list) and installs and isinstance(installs[0], dict):
            first = installs[0]
            manager = first.get("manager")
            package = first.get("package")
            if manager and package:
                hint = f"{manager} install {package}"
            elif manager:
                hint = str(manager)
        requirement = entry.get("version_requirement")
        command = command.rsplit("/", 1)[-1] if command.startswith("/") else command
        tools[command] = Tool(
            command=command,
            required=bool(entry.get("required", True)),
            version_requirement=str(requirement) if requirement else None,
            install_hint=hint,
        )
    return tools, True, None


def load(root: Path, reference: str | None = None) -> Package:
    root = root.resolve()
    main = root / "main.ts"
    source = main.read_text(encoding="utf-8", errors="replace") if main.is_file() else ""
    front = fm.extract(source) if source else fm.Frontmatter(error="main.ts is missing")
    inferred, _ = _reference_for(root)
    version = front.metadata.get("version")
    package = Package(
        root=root,
        reference=reference or inferred,
        version=str(version) if version is not None else None,
        source=source,
        frontmatter=front,
    )
    package.tools, package.deps_present, package.deps_error = _load_tools(root)

    manifest = root / "manifest.json"
    if manifest.is_file():
        try:
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            package.manifest = loaded if isinstance(loaded, dict) else None
            if package.manifest is None:
                package.manifest_error = "manifest.json is not an object"
        except (OSError, json.JSONDecodeError) as error:
            package.manifest_error = f"manifest.json could not be parsed: {error}"

    resources = root / "resources"
    if resources.is_dir():
        for path in sorted(p for p in resources.rglob("*") if p.is_file()):
            relative = str(path.relative_to(resources))
            package.resources[relative] = path
            if path.suffix == ".py":
                package.python_resources.append(path)
            elif path.suffix in {".sh", ".bash"}:
                package.shell_resources.append(path)
            elif path.suffix in {".js", ".mjs", ".cjs", ".ts"}:
                package.script_resources.append(path)

    package.digest = _install_receipt_digest(root) or _content_digest(root)
    return package
