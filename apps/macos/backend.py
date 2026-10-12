#!/usr/bin/env python3
"""Private stdio bridge for Play for Mac. No HTTP listener or Rote source changes."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.request import Request, urlopen

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
OUTPUT = sys.stdout
OUTPUT_LOCK = threading.Lock()


class UserError(Exception):
    def __init__(self, message, code="operation"):
        super().__init__(message)
        self.code = code


def emit(kind: str, **fields):
    with OUTPUT_LOCK:
        OUTPUT.write(json.dumps({"type": kind, **fields}, ensure_ascii=False) + "\n")
        OUTPUT.flush()


def version_key(value):
    match = re.search(r"(?:^|\s|v)(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def read_json(path: Path, default=None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def command(args, *, stdin="", timeout=45):
    return subprocess.run(list(args), input=stdin, capture_output=True, text=True,
                          check=False, timeout=timeout)


def configure_path():
    home = Path.home()
    paths = [str(home / ".local/bin"), str(home / ".cargo/bin"),
             str(home / ".bun/bin"), str(home / ".volta/bin"),
             str(home / ".local/share/mise/shims"), "/opt/homebrew/bin", "/usr/local/bin"]
    paths += [str(p) for p in sorted((home / ".nvm/versions/node").glob("*/bin"), reverse=True)]
    paths += os.environ.get("PATH", "").split(os.pathsep)
    paths += ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(p for p in paths if p))
    os.environ["NO_COLOR"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def secure_extract(archive: Path, destination: Path):
    """Release archives may contain regular files/directories under exactly one root."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        roots = set()
        total = 0
        for member in members:
            parts = Path(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts:
                raise UserError("The release archive contains an unsafe path.")
            if not (member.isfile() or member.isdir()):
                raise UserError("The release archive contains an unsupported entry.")
            total += member.size
            if total > 512 * 1024 * 1024 or len(members) > 25000:
                raise UserError("The release archive exceeds the supported size.")
            roots.add(parts[0])
        if len(roots) != 1:
            raise UserError("The release archive has an unexpected layout.")
        for member in members:
            parts = Path(member.name).parts[1:]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise UserError("The release archive contains an unreadable file.")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


class Bridge:
    def __init__(self, bundled: Path, state_root: Path | None = None):
        self.bundled = bundled.resolve()
        self.root = state_root or Path.home() / "Library/Application Support/Modiqo Play"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.payload = {}
        self._bootstrap: ModuleType | None = None

    @property
    def bootstrap(self) -> ModuleType:
        if self._bootstrap is None:
            raise UserError("The Play runtime has not been loaded.")
        return self._bootstrap

    def load_runtime(self, source=None):
        sys.path.insert(0, str((source or self.bundled) / "scripts/lib"))
        from play import bootstrap
        self._bootstrap = bootstrap
        return bootstrap

    def rote(self):
        value = shutil.which("rote")
        if not value:
            raise UserError("Prepare Rote before signing in or managing your organization.")
        return value

    def identity(self):
        from play.search_transport import registry_config
        rote = shutil.which("rote")
        if not rote:
            return {"state": "required", "email": "", "userID": ""}
        try:
            check = command([rote, "whoami", "--check"], timeout=30)
            if check.returncode:
                return {"state": "required" if check.returncode == 77 else "unavailable", "email": "", "userID": ""}
            config = registry_config()
            return {"state": "authenticated", "email": str(config.get("email") or ""),
                    "userID": str(config.get("user_id") or "")}
        except (OSError, subprocess.TimeoutExpired):
            return {"state": "unavailable", "email": "", "userID": ""}

    def require_identity(self):
        identity = self.identity()
        if identity["state"] != "authenticated":
            raise UserError("Sign in to continue. If you are already signed in, check your connection and refresh.")
        return identity

    def harnesses(self):
        b = self.bootstrap
        result = []
        from play.harnesses import HARNESS_SPECS
        specs = {s.id: s for s in HARNESS_SPECS}
        for target in b.discover_targets(top_k=7):
            installed = target.play_skill_installed
            version = None
            for root in target.skill_roots:
                candidate = Path(root) / "play/VERSION"
                if candidate.is_file():
                    version = candidate.read_text().strip()
                    break
            if target.id in {"codex", "claude"} and target.command:
                try:
                    response = command(b._plugin_list_command(target.id, target.command), timeout=12)
                    if response.returncode == 0:
                        record = b._play_plugin_record(target.id, json.loads(response.stdout),
                                                      scope="user" if target.id == "claude" else None)
                        if record:
                            installed = True
                            version = str(record.get("version") or version or "unknown")
                except (ValueError, OSError, subprocess.TimeoutExpired, b.BootstrapError):
                    pass
            result.append({"id": target.id, "name": target.label, "detected": target.detected,
                           "installed": installed, "version": version or "", "entry": specs[target.id].play_entry,
                           "commandAvailable": bool(target.command) or (target.id == "cursor" and Path("/Applications/Cursor.app").exists()) or (target.id == "codex" and Path("/Applications/Codex.app").exists()), "selected": target.selected})
        return result

    def status(self, payload):
        b = self.bootstrap
        rote = shutil.which("rote")
        version = ""
        if rote:
            response = command([rote, "--version"], timeout=10)
            if response.returncode == 0:
                version = response.stdout.strip()[:120]
        active = read_json(self.root / "active-install.json", {})
        # An older bridge could fail after bootstrap already wrote its receipt.
        # Reconcile from that authoritative receipt without repeating installation.
        identifier = active.get("runID", "")
        if active.get("status") == "running" and re.fullmatch(r"mac-[a-f0-9]{32}", identifier):
            receipt_path = b._report_root() / "runs" / f"{identifier}.json"
            receipt = read_json(receipt_path)
            if isinstance(receipt, dict) and receipt.get("run_id") == identifier:
                public = self.public_report(receipt, receipt_path)
                save_json(self.root / "last-report.json", public)
                active["status"] = public["status"]
                save_json(self.root / "active-install.json", active)
        return {"playVersion": b._installed_play_version() or "", "bundledVersion": b._play_version(),
                "roteVersion": version, "roteInstalled": bool(rote), "roteReady": version_key(version) >= (0, 85, 0), "identity": self.identity(),
                "harnesses": self.harnesses(), "architecture": platform.machine(),
                "interrupted": active.get("status") == "running", "lastReport": read_json(self.root / "last-report.json")}

    def prepare(self, payload):
        if payload.get("approved") is not True:
            raise UserError("Review and approve the Rote prerequisite first.")
        rote = shutil.which("rote")
        if rote:
            current = command([rote, "--version"], timeout=10)
            if current.returncode == 0 and version_key(current.stdout) >= (0, 85, 0):
                return {"installed": True}
            emit("progress", label="Updating Rote for email sign-in", state="running")
            result = command([rote, "self-update", "--yes"], timeout=900)
            verified = command([rote, "--version"], timeout=10)
            if result.returncode or verified.returncode or version_key(verified.stdout) < (0, 85, 0):
                raise UserError("Rote 0.85.0 or newer is needed for email sign-in. Update Rote, then retry.")
            return {"installed": True}
        emit("progress", label="Preparing Rote and its runtimes", state="running")
        result = command(self.bootstrap._official_rote_install_command(), timeout=900)
        if result.returncode or not shutil.which("rote"):
            raise UserError("Rote setup did not finish. Check ~/.rote/log/install.log, then try again.")
        return {"installed": True}

    def login(self, payload):
        provider = payload.get("provider")
        if provider not in {"google", "github"}:
            raise UserError("Choose Google or GitHub.")
        emit("progress", label=f"Finish signing in with {provider.title()} in your browser", state="running")
        result = command([self.rote(), "login", "--provider", provider], timeout=300)
        if result.returncode:
            raise UserError("Browser sign-in did not finish. Try again or use email.")
        from play.identity import remember_login_provider
        identity = self.require_identity()
        remember_login_provider(provider)
        return identity

    def email(self, payload):
        from play.email_login import EmailLogin
        email = str(payload.get("email", "")).strip()
        action = payload.get("operation")
        if action not in {"send", "verify"}:
            raise UserError("Choose send or verify.")
        metadata = read_json(self.root / "email-attempt.json", {})
        login = EmailLogin(self.rote())
        login.email = metadata.get("email", "")
        # Monotonic clocks reset at reboot; persist wall time and reconstruct the
        # short cooldown instead of retaining a clock value from another boot.
        login.sent_at = time.monotonic() - max(0, time.time() - metadata["created"]) if metadata.get("created") else 0
        login.failures = int(metadata.get("failures", 0))
        if action == "verify" and time.time() - metadata.get("created", 0) > 600:
            raise UserError("That sign-in attempt expired. Request a new code.")
        status, message = login.submit({"action": action, "email": email, "code": str(payload.get("code", ""))})
        save_json(self.root / "email-attempt.json", {"email": login.email,
                  "failures": login.failures, "created": time.time() if action == "send" and status == 200 else metadata.get("created", 0)})
        if status != 200:
            raise UserError(message)
        if action == "verify":
            from play.identity import remember_login_provider
            identity = self.require_identity()
            remember_login_provider("email")
            (self.root / "email-attempt.json").unlink(missing_ok=True)
            return identity
        return {"sent": True}

    def organizations(self, payload):
        identity = self.require_identity()
        result = command([self.rote(), "registry", "org", "list", "--json"])
        if result.returncode:
            raise UserError("Organizations could not be loaded. Check your connection and retry.")
        raw = json.loads(result.stdout)
        rows = raw if isinstance(raw, list) else raw.get("organizations", raw.get("orgs", []))
        if not isinstance(rows, list):
            raise UserError("The registry returned an unexpected organization list.")
        return {"organizations": [{"id": str(row.get("id", "")), "slug": str(row.get("slug", "")),
                 "name": str(row.get("display_name") or row.get("name") or row.get("slug") or "Organization"),
                 "owned": row.get("owner_id") == identity["userID"] and bool(identity["userID"]),
                 "role": str(row.get("role", "member"))} for row in rows if isinstance(row, dict)]}

    def create_org(self, payload):
        self.require_identity()
        slug = str(payload.get("slug", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not SLUG.fullmatch(slug) or not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
            raise UserError("Enter a company name and a lowercase organization handle using letters, numbers, or hyphens.")
        result = command([self.rote(), "registry", "org", "create", "--slug", slug, "--name", name])
        if result.returncode:
            raise UserError("The organization was not created. The handle may be taken; check your account page before retrying.")
        return {"slug": slug, "name": name}

    def invite(self, payload):
        self.require_identity()
        slug, email, role = str(payload.get("slug", "")), str(payload.get("email", "")).strip(), payload.get("role")
        if not SLUG.fullmatch(slug) or len(email) > 254 or not EMAIL.fullmatch(email) or role not in {"admin", "developer", "reader"}:
            raise UserError("Enter a valid organization, colleague email, and role.")
        result = command([self.rote(), "registry", "org", "invite", slug, email, "--role", role])
        if result.returncode:
            raise UserError("The invitation could not be confirmed. Check pending invitations on your account page before retrying.")
        return {"sent": True, "email": email}

    def updates(self, payload):
        request = Request("https://api.github.com/repos/modiqo/play/releases/latest", headers={"Accept": "application/vnd.github+json", "User-Agent": "Modiqo-Play-Mac"})
        with urlopen(request, timeout=25) as response:
            release = json.loads(response.read(1_000_000))
        version = str(release.get("tag_name", "")).removeprefix("v")
        if not VERSION.fullmatch(version) or release.get("prerelease") or release.get("draft"):
            raise UserError("A stable Play release could not be confirmed.")
        bundled = self.bootstrap._play_version()
        version = max([version, bundled], key=version_key)
        installed = self.bootstrap._installed_play_version()
        rote = self.bootstrap._probe_update(shutil.which("rote"), lambda args: command(args, timeout=35))
        return {"version": version, "installedVersion": installed or "", "available": version_key(version) > version_key(installed),
                "roteStatus": rote["status"], "releaseURL": f"https://github.com/modiqo/play/releases/tag/v{version}"}

    def release_source(self, version):
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise UserError("Choose a valid stable Play release.")
        installed = [self.bootstrap._installed_play_version()] + [x["version"] for x in self.harnesses() if x["installed"]]
        if max(map(version_key, installed)) > version_key(version):
            raise UserError("This Mac has a newer Play version. Check for a newer release; downgrades are disabled.")
        if version == self.bootstrap._play_version():
            return self.bundled
        root = self.root / "releases" / version
        if (root / ".download-complete.json").is_file() and (root / "VERSION").read_text().strip() == version:
            return root
        emit("progress", label=f"Downloading Play {version}", state="running")
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            archive = Path(temporary) / "release.tar.gz"
            request = Request(f"https://github.com/modiqo/play/archive/refs/tags/v{version}.tar.gz", headers={"User-Agent": "Modiqo-Play-Mac"})
            digest = hashlib.sha256()
            size = 0
            with urlopen(request, timeout=60) as response, archive.open("wb") as output:
                while chunk := response.read(1_048_576):
                    size += len(chunk)
                    if size > 128 * 1024 * 1024:
                        raise UserError("The release download exceeds the supported size.")
                    digest.update(chunk)
                    output.write(chunk)
            extracted = Path(temporary) / "source"
            extracted.mkdir()
            secure_extract(archive, extracted)
            if not (extracted / "VERSION").is_file() or (extracted / "VERSION").read_text().strip() != version or not (extracted / "scripts/bin/play-bootstrap").is_file():
                raise UserError("The downloaded release does not match the selected version.")
            root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if root.exists():
                shutil.rmtree(root)
            shutil.move(str(extracted), root)
            save_json(root / ".download-complete.json", {"version": version, "sha256": digest.hexdigest()})
        return root

    def runtime_for_source(self, source):
        # Load the chosen release's installer, not the bundled version's installer.
        for key in list(sys.modules):
            if key == "play" or key.startswith("play."):
                del sys.modules[key]
        return self.load_runtime(source)

    def plan(self, payload):
        self.require_identity()
        requested = payload.get("harnesses")
        if not isinstance(requested, list) or not requested or not all(isinstance(x, str) and x in self.bootstrap.SUPPORTED_HARNESSES for x in requested):
            raise UserError("Select at least one detected harness.")
        source = self.release_source(payload.get("version"))
        b = self.runtime_for_source(source)
        plan = b.build_plan(requested=requested, top_k=7, runner=lambda args: command(args, timeout=60))
        if sorted(plan["selected_harnesses"]) != sorted(set(requested)):
            raise UserError("A selected harness is no longer detected. Refresh and review your selection.")
        if plan["rote"]["update"]["status"] == "check_failed":
            raise UserError("Rote update availability could not be checked. Retry before applying the paired update.")
        identifier = uuid.uuid4().hex
        save_json(self.root / "plans" / f"{identifier}.json", {"source": str(source), "plan": plan, "created": time.time()})
        return {"id": identifier, "version": plan["play_version"], "installedVersion": plan["play"]["installed_version"] or "",
                "roteVersion": plan["rote"]["version"] or "", "roteAction": plan["rote"]["update"]["status"],
                "harnesses": plan["selected_harnesses"], "actions": [str(x["effect"]) for x in plan["actions"] if x.get("recommended", True) and "tulving" not in x["id"]],
                "note": "Play configuration is backed up and restored if Play verification fails. Rote updates are forward-only."}

    def install(self, payload):
        identifier = payload.get("planID", "")
        if payload.get("approved") is not True or not re.fullmatch(r"[a-f0-9]{32}", str(identifier)):
            raise UserError("Review and approve an installation plan first.")
        path = self.root / "plans" / f"{identifier}.json"
        saved = read_json(path)
        if not saved or time.time() - saved["created"] > 900:
            raise UserError("The installation plan expired. Review a fresh plan.")
        self.require_identity()
        source = Path(saved["source"]).resolve()
        if source != self.bundled and self.root / "releases" not in source.parents:
            raise UserError("The installation source is outside the release cache.")
        b = self.runtime_for_source(source)
        fresh = b.build_plan(requested=saved["plan"]["selected_harnesses"], top_k=7, runner=lambda args: command(args, timeout=60))
        if fresh["plan_id"] != saved["plan"]["plan_id"]:
            raise UserError("Your setup changed since review. Review a fresh plan before applying it.")
        self.persist_runtime()
        path.unlink()
        run_id = "mac-" + uuid.uuid4().hex
        marker = {"runID": run_id, "status": "running", "started": time.time(), "phase": "Starting"}
        save_json(self.root / "active-install.json", marker)

        state_root = self.root
        class Progress(b.Progress):
            def __init__(self):
                super().__init__(enabled=False)
            def start_phase(self, label):
                marker["phase"] = label
                save_json(state_root / "active-install.json", marker)
                emit("progress", label=label, state="phase")
            def begin(self, label):
                emit("progress", label=label, state="running")
                return b.ProgressToken(label, time.monotonic())
            def finish(self, token, *, ok=True):
                emit("progress", label=token.label, state="complete" if ok else "failed")

        report = b.apply(source, requested=fresh["selected_harnesses"], top_k=7,
                         runner=lambda args: command(args, timeout=900), prepared_plan=fresh,
                         expected_plan_id=fresh["plan_id"], run_id=run_id, progress=Progress())
        # apply() owns receipt creation. Calling write_report() again raises an
        # error for every outcome, including successful installs and rollbacks.
        receipt_path = Path(report["report_paths"]["json"])
        public = self.public_report(report, receipt_path)
        save_json(self.root / "last-report.json", public)
        marker["status"] = report["status"]
        save_json(self.root / "active-install.json", marker)
        return public

    def public_report(self, report, receipt_path):
        failed = [step for step in report.get("steps", []) if step.get("status") in {"failed", "blocked", "human_action_required"}]
        # Only curated error classifications enter the copyable report. Raw CLI
        # output can contain private paths, account details, or credentials.
        issues = []
        for step in failed:
            detail = str(step.get("detail", ""))
            if "No such file or directory" in detail:
                reason = "A required file or harness folder was missing."
            elif "locked Python dependencies" in detail:
                reason = "Play’s Python dependencies could not be prepared."
            elif "permission denied" in detail.lower():
                reason = "The installer could not access a required file."
            else:
                reason = "This step failed. The local receipt contains its diagnostics."
            issues.append({"step": re.sub(r"[^a-zA-Z0-9_-]", "", str(step.get("id", "unknown")))[:100], "reason": reason})
        return {"status": report["status"], "runID": report["run_id"], "reportPath": str(receipt_path),
                "harnesses": report.get("selected_harnesses", []), "version": report.get("play", {}).get("target_version", ""),
                "backupAvailable": bool(report.get("backup")), "failures": [item["step"] for item in issues],
                "issues": issues, "rolledBack": report.get("backup", {}).get("auto_restored") is True}

    def persist_runtime(self):
        """Installed venvs must survive moving the app or ejecting its DMG."""
        bundled = os.environ.get("PLAY_DESKTOP_RUNTIME")
        if not bundled:
            raise UserError("Open the packaged Mac app to install Play.")
        origin = Path(bundled).resolve()
        manifest = origin / "runtime.json"
        if not manifest.is_file() or not (origin / "python/bin/python3").is_file():
            raise UserError("The bundled Python runtime is missing. Download the app again.")
        fingerprint = hashlib.sha256(manifest.read_bytes()).hexdigest()[:20]
        destination = self.root / "runtime" / fingerprint
        if not (destination / "runtime.json").is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
                staged = Path(temporary) / "runtime"
                shutil.copytree(origin, staged, symlinks=True)
                staged.rename(destination)
        python = destination / "python/bin/python3"
        os.environ["PATH"] = str(destination / "bin") + os.pathsep + str(python.parent) + os.pathsep + os.environ["PATH"]
        os.environ["UV_PYTHON"] = str(python)
        os.environ["UV_PYTHON_DOWNLOADS"] = "never"
        sys.executable = str(python)

    def search(self, payload):
        self.require_identity()
        from play.search import search_published, SearchError
        query = str(payload.get("query", "")).strip()
        if not 2 <= len(query) <= 1000:
            raise UserError("Enter a search between 2 and 1,000 characters.")
        scope = payload.get("scope", "all")
        if scope not in {"all", "community", "personal", "organizations", "org"}:
            raise UserError("Choose a supported search scope.")
        org = payload.get("org") if scope == "org" else None
        if scope == "org" and (not isinstance(org, str) or not SLUG.fullmatch(org)):
            raise UserError("Choose an organization to search.")
        try:
            response = search_published(query, public=scope == "community", org=org, limit=8, timeout_seconds=35)
        except SearchError as error:
            if "HTTP 401" in str(error):
                raise UserError("The search service could not accept your Rote sign-in. Sign in again, then retry. No private results were loaded.", "signin") from None
            if "HTTP 403" in str(error):
                raise UserError("Your account cannot access this search scope. Check organization membership on your account page.") from None
            raise UserError("Published Play search is unavailable or could not verify its results. Retry shortly. Your search scope has stayed the same.") from None
        kinds = {"personal": {"personal"}, "organizations": {"organization"}}.get(scope)
        rows = [row for row in response["results"] if not kinds or row["group_kind"] in kinds]
        return {"complete": response["complete"], "results": [{"id": x["exact_reference"], "title": x["name"],
                "description": x["description"], "reference": x["exact_reference"], "url": x["uri"],
                "groupID": x["group_id"], "groupLabel": x["group_label"], "groupKind": x["group_kind"],
                "relevance": x["relevance_status"], "visibility": "private" if x["primary_scope"] == "remote_private" else "public"} for x in rows]}

    def launch(self, payload):
        from play.harnesses import HARNESS_BY_ID, detect_harness
        identifier = payload.get("harness")
        if identifier not in HARNESS_BY_ID:
            raise UserError("Choose a supported harness.")
        spec = HARNESS_BY_ID[identifier]
        present, executable = detect_harness(spec)
        if not present:
            raise UserError("That harness is no longer detected. Refresh your setup.")
        app_names = {"cursor": "Cursor", "codex": "Codex"}
        name = app_names.get(identifier)
        if name and any((root / f"{name}.app").exists() for root in [Path('/Applications'), Path.home() / 'Applications']):
            result = command(["/usr/bin/open", "-a", name])
        else:
            if not executable:
                raise UserError("The harness command is not on PATH. Open the harness yourself and paste the copied prompt.")
            script = self.root / "launchers" / f"{identifier}.command"
            script.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            script.write_text("#!/bin/sh\nexport PATH=" + shlex.quote(os.environ["PATH"]) + "\ncd " + shlex.quote(str(Path.home())) + "\nexec " + shlex.join([executable, *spec.start_command[1:]]) + "\n")
            script.chmod(0o700)
            result = command(["/usr/bin/open", "-a", "Terminal", str(script)])
        if result.returncode:
            raise UserError("The harness could not be opened. Open it yourself and paste the prompt.")
        return {"opened": True}

    def dispatch(self, action, payload):
        actions = {name: getattr(self, name) for name in ["status", "prepare", "login", "email", "organizations", "create_org", "invite", "updates", "plan", "install", "search", "launch"]}
        if action not in actions:
            raise UserError("Unknown desktop action.")
        self.load_runtime()
        with (self.root / "operation.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UserError("Another Play window is working. Wait for it to finish.") from None
            return actions[action](payload)


def main():
    os.umask(0o077)
    configure_path()
    try:
        if len(sys.argv) != 3:
            raise UserError("The desktop bridge needs a source directory and action.")
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise UserError("The desktop request is too large.")
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise UserError("Invalid desktop request.")
        bridge = Bridge(Path(sys.argv[1]))
        # Installer diagnostics stay in its existing receipts, not the UI protocol.
        with contextlib.redirect_stdout(io.StringIO()):
            result = bridge.dispatch(sys.argv[2], payload)
        emit("result", data=result)
    except UserError as error:
        emit("error", message=str(error), code=error.code)
        return 1
    except subprocess.TimeoutExpired:
        emit("error", message="The operation timed out. Check your connection and retry. Review your account before resending an invitation.")
        return 1
    except Exception:
        # Never return captured CLI output, environment variables, or token-bearing responses.
        emit("error", message="The operation could not finish. Check your connection and installed tools, then retry. Installation receipts are in ~/.local/state/play-bootstrap/runs/.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
