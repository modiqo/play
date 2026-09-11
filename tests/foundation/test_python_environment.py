from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts.lib.play.python_environment import (
    BOOTSTRAP_GUARD_VARIABLE,
    DEFAULT_INDEX_URL,
    INDEX_OVERRIDE_VARIABLE,
    RUNTIME_MODULES,
    PackageIndex,
    PackageIndexError,
    ensure_runtime,
    explain_bootstrap_failure,
    lock_indexes,
    lock_matches_index,
    looks_like_index_failure,
    missing_runtime_modules,
    pip_config_index,
    pip_install_command,
    record_package_index,
    resolve_package_index,
    uv_environment,
    uv_run_command,
    uv_sync_command,
)

ROOT = Path(__file__).resolve().parents[2]
MIRROR = "https://factory.example.com/api/pypi/simple"


def _lock(root: Path, *registries: str) -> None:
    blocks = "\n".join(
        f'[[package]]\nname = "pkg{index}"\nversion = "1.0"\nsource = {{ registry = "{registry}" }}\n'
        for index, registry in enumerate(registries)
    )
    (root / "uv.lock").write_text("version = 1\n" + blocks, encoding="utf-8")


class PackageIndexResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.environ = {"HOME": str(self.home), "PATH": "/usr/bin"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_defaults_to_pypi_when_nothing_is_configured(self) -> None:
        index = resolve_package_index(self.root, self.environ)

        self.assertEqual(PackageIndex(DEFAULT_INDEX_URL, "default"), index)
        self.assertFalse(index.overrides_default)
        self.assertIn("uv default", index.describe())

    def test_play_override_wins_over_uv_pip_and_recorded_sources(self) -> None:
        (self.root / ".play-install.json").write_text(
            json.dumps({"schema": "x", "python_index": {"url": "https://recorded/simple"}}),
            encoding="utf-8",
        )
        environ = {
            **self.environ,
            INDEX_OVERRIDE_VARIABLE: MIRROR,
            "UV_DEFAULT_INDEX": "https://uv/simple",
            "PIP_INDEX_URL": "https://pip/simple",
        }

        self.assertEqual(PackageIndex(MIRROR, INDEX_OVERRIDE_VARIABLE), resolve_package_index(self.root, environ))
        del environ[INDEX_OVERRIDE_VARIABLE]
        self.assertEqual(PackageIndex("https://uv/simple", "UV_DEFAULT_INDEX"), resolve_package_index(self.root, environ))
        del environ["UV_DEFAULT_INDEX"]
        recorded = resolve_package_index(self.root, environ)
        self.assertEqual("https://recorded/simple", recorded.url)
        self.assertIn(".play-install.json", recorded.source)
        (self.root / ".play-install.json").unlink()
        self.assertEqual(PackageIndex("https://pip/simple", "PIP_INDEX_URL"), resolve_package_index(self.root, environ))

    def test_pip_configuration_file_index_is_honored(self) -> None:
        config = self.home / ".config" / "pip" / "pip.conf"
        config.parent.mkdir(parents=True)
        config.write_text(f"[global]\nindex-url = {MIRROR}\ntimeout = 60\n", encoding="utf-8")

        index = resolve_package_index(self.root, self.environ)

        self.assertEqual(MIRROR, index.url)
        self.assertEqual(str(config), index.source)
        self.assertTrue(index.overrides_default)
        self.assertIsNone(pip_config_index({**self.environ, "PIP_CONFIG_FILE": str(self.root / "absent.conf")}))

    def test_invalid_override_is_rejected_instead_of_handed_to_uv(self) -> None:
        for value in ("factory.example.com/simple", "https://bad host/simple"):
            with self.subTest(value=value), self.assertRaises(PackageIndexError):
                resolve_package_index(self.root, {**self.environ, INDEX_OVERRIDE_VARIABLE: value})

    def test_blank_override_means_unset(self) -> None:
        index = resolve_package_index(self.root, {**self.environ, INDEX_OVERRIDE_VARIABLE: "   "})

        self.assertEqual("default", index.source)

    def test_uv_native_variables_are_not_duplicated_into_the_environment(self) -> None:
        native = uv_environment({"UV_DEFAULT_INDEX": MIRROR}, PackageIndex(MIRROR, "UV_DEFAULT_INDEX"))
        derived = uv_environment({"PIP_INDEX_URL": MIRROR}, PackageIndex(MIRROR, "PIP_INDEX_URL"))
        default = uv_environment({}, PackageIndex(DEFAULT_INDEX_URL, "default"))

        self.assertEqual({"UV_DEFAULT_INDEX": MIRROR}, native)
        self.assertEqual(MIRROR, derived["UV_DEFAULT_INDEX"])
        self.assertNotIn("UV_DEFAULT_INDEX", default)


class LockAndCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repository_lock_pins_pypi_only(self) -> None:
        self.assertEqual((DEFAULT_INDEX_URL,), lock_indexes(ROOT))

    def test_sync_keeps_locked_only_when_the_lock_and_index_agree(self) -> None:
        _lock(self.root, DEFAULT_INDEX_URL, DEFAULT_INDEX_URL)
        default = PackageIndex(DEFAULT_INDEX_URL, "default")
        mirror = PackageIndex(MIRROR, "PIP_INDEX_URL")

        self.assertTrue(lock_matches_index(self.root, default))
        self.assertFalse(lock_matches_index(self.root, mirror))
        self.assertEqual(
            ["uv", "sync", "--locked", "--no-dev", "--inexact", "--project", str(self.root)],
            uv_sync_command("uv", self.root, default),
        )
        self.assertEqual(
            ["uv", "sync", "--no-dev", "--inexact", "--project", str(self.root)],
            uv_sync_command("uv", self.root, mirror),
        )
        _lock(self.root, MIRROR + "/")
        self.assertTrue(lock_matches_index(self.root, mirror))
        self.assertIn("--locked", uv_sync_command("uv", self.root, mirror))

    def test_missing_lock_never_blocks_the_locked_sync(self) -> None:
        self.assertEqual((), lock_indexes(self.root))
        self.assertTrue(lock_matches_index(self.root, PackageIndex(MIRROR, "PIP_INDEX_URL")))

    def test_run_command_skips_the_dev_group(self) -> None:
        command = uv_run_command("uv", self.root, self.root / "scripts" / "bin" / "play-machine", ["describe"])

        self.assertEqual(
            ["uv", "run", "--no-dev", "--project", str(self.root), str(self.root / "scripts" / "bin" / "play-machine"), "describe"],
            command,
        )

    def test_pip_fallback_names_every_pinned_requirement_and_the_index(self) -> None:
        command = pip_install_command(PackageIndex(MIRROR, "PIP_INDEX_URL"))

        self.assertIn(f"--index-url {MIRROR}", command)
        for requirement in ("ast-grep-py", "jsonschema", "python-statemachine[yaml]", "PyYAML"):
            self.assertIn(requirement, command)
        self.assertNotIn("--index-url", pip_install_command(PackageIndex(DEFAULT_INDEX_URL, "default")))

    def test_failure_explanation_names_the_index_and_the_overridden_pin(self) -> None:
        _lock(self.root, DEFAULT_INDEX_URL)
        mirror = explain_bootstrap_failure(self.root, PackageIndex(MIRROR, "PIP_INDEX_URL"), tool="play-machine")
        default = explain_bootstrap_failure(self.root, PackageIndex(DEFAULT_INDEX_URL, "default"), tool="play-machine")

        self.assertIn(f"{MIRROR} (from PIP_INDEX_URL)", mirror)
        self.assertIn("uv re-resolved against the index above", mirror)
        self.assertIn(INDEX_OVERRIDE_VARIABLE, default)
        self.assertIn("private package index", default)
        self.assertTrue(looks_like_index_failure("error: Failed to fetch: `https://pypi.org/simple/pyyaml/`"))
        self.assertFalse(looks_like_index_failure("Traceback (most recent call last): KeyError"))

    def test_recording_the_index_updates_only_an_existing_marker(self) -> None:
        mirror = PackageIndex(MIRROR, "PIP_INDEX_URL")
        self.assertFalse(record_package_index(self.root, mirror))
        marker = self.root / ".play-install.json"
        marker.write_text(json.dumps({"schema": "play.portable-install/v1", "version": "0.4.97"}), encoding="utf-8")

        self.assertTrue(record_package_index(self.root, mirror))
        self.assertFalse(record_package_index(self.root, mirror))
        payload = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual({"url": MIRROR, "source": "PIP_INDEX_URL"}, payload["python_index"])
        self.assertEqual("0.4.97", payload["version"])
        self.assertEqual(MIRROR, resolve_package_index(self.root, {"HOME": str(self.root)}).url)

        self.assertTrue(record_package_index(self.root, PackageIndex(DEFAULT_INDEX_URL, "default")))
        self.assertNotIn("python_index", json.loads(marker.read_text(encoding="utf-8")))


class EnsureRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _lock(self.root, DEFAULT_INDEX_URL)
        self.script = self.root / "scripts" / "bin" / "play-machine"
        self.absent = lambda name: None
        self.present = lambda name: object()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_every_pinned_module_is_probed(self) -> None:
        self.assertEqual(("ast_grep_py", "jsonschema", "statemachine", "yaml"), RUNTIME_MODULES)
        self.assertEqual(list(RUNTIME_MODULES), missing_runtime_modules(self.absent))
        self.assertEqual(["yaml"], missing_runtime_modules(lambda name: None if name == "yaml" else object()))
        self.assertEqual([], missing_runtime_modules(self.present))

    def test_ready_environment_returns_without_touching_uv(self) -> None:
        which = MagicMock(return_value="/bin/uv")

        ensure_runtime("play-machine", self.root, self.script, ["describe"], environ={}, find_spec=self.present, which=which)

        which.assert_not_called()

    def test_missing_uv_explains_the_manual_install(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            ensure_runtime("play-machine", self.root, self.script, [], environ={"PIP_INDEX_URL": MIRROR}, find_spec=self.absent, which=lambda name: None)

        message = str(caught.exception)
        self.assertIn("play-machine requires uv", message)
        self.assertIn("ast_grep_py, jsonschema, statemachine, yaml", message)
        self.assertIn(f"--index-url {MIRROR}", message)

    def test_advisory_launcher_continues_without_uv(self) -> None:
        ensure_runtime("play-audit", self.root, self.script, [], environ={}, find_spec=self.absent, which=lambda name: None, advisory=True)

    def test_existing_environment_re_enters_uv_with_the_resolved_index(self) -> None:
        (self.root / ".venv").mkdir()
        execve = MagicMock()

        ensure_runtime(
            "play-machine",
            self.root,
            self.script,
            ["run-until-yield", "--stdin"],
            environ={"PIP_INDEX_URL": MIRROR, "PATH": "/usr/bin"},
            find_spec=self.absent,
            which=lambda name: "/bin/uv",
            execve=execve,
            extra_environment={"PLAY_AUDIT_HOST_PATH": "/usr/bin"},
        )

        execve.assert_called_once()
        path, argv, env = execve.call_args.args
        self.assertEqual("/bin/uv", path)
        self.assertEqual(["/bin/uv", "run", "--no-dev", "--project", str(self.root), str(self.script), "run-until-yield", "--stdin"], argv)
        self.assertEqual(MIRROR, env["UV_DEFAULT_INDEX"])
        self.assertEqual("1", env[BOOTSTRAP_GUARD_VARIABLE])
        self.assertEqual("/usr/bin", env["PLAY_AUDIT_HOST_PATH"])

    def test_first_materialization_explains_a_download_failure(self) -> None:
        stderr = MagicMock()
        stderr.write = MagicMock()
        run = MagicMock(
            return_value=subprocess.CompletedProcess(
                ["uv"], 2, stdout="", stderr="error: Failed to fetch: `https://pypi.org/simple/pyyaml/`\n"
            )
        )

        with self.assertRaises(SystemExit) as caught:
            ensure_runtime("play-machine", self.root, self.script, [], environ={}, find_spec=self.absent, which=lambda name: "/bin/uv", run=run, stderr=stderr)

        self.assertEqual(2, caught.exception.code)
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("Failed to fetch", written)
        self.assertIn("Play could not download its pinned Python packages", written)
        self.assertIn(INDEX_OVERRIDE_VARIABLE, written)
        kwargs = run.call_args.kwargs
        self.assertEqual("1", kwargs["env"][BOOTSTRAP_GUARD_VARIABLE])
        self.assertEqual(subprocess.PIPE, kwargs["stderr"])

    def test_successful_first_materialization_exits_with_the_child_status(self) -> None:
        run = MagicMock(return_value=subprocess.CompletedProcess(["uv"], 0, stdout="", stderr=""))
        stderr = MagicMock()

        with self.assertRaises(SystemExit) as caught:
            ensure_runtime("play-machine", self.root, self.script, [], environ={}, find_spec=self.absent, which=lambda name: "/bin/uv", run=run, stderr=stderr)

        self.assertEqual(0, caught.exception.code)

    def test_guarded_re_entry_never_loops(self) -> None:
        which = MagicMock(return_value="/bin/uv")

        with self.assertRaises(SystemExit) as caught:
            ensure_runtime("play-machine", self.root, self.script, [], environ={BOOTSTRAP_GUARD_VARIABLE: "1"}, find_spec=self.absent, which=which)

        which.assert_not_called()
        self.assertIn("still lacks", str(caught.exception))

    def test_launchers_share_the_bootstrap_contract(self) -> None:
        for name in ("play-machine", "play-intercept", "play-journey", "play-routing", "play-audit", "play-audit-corpus"):
            with self.subTest(launcher=name):
                text = (ROOT / "scripts" / "bin" / name).read_text(encoding="utf-8")
                self.assertIn("from play.python_environment import ensure_runtime", text)
                self.assertNotIn("execve", text)
                self.assertNotIn("_UV_BOOTSTRAPPED", text)

    def test_module_stays_stdlib_only(self) -> None:
        result = subprocess.run(
            [
                "/usr/bin/env",
                "python3",
                "-I",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import play.python_environment",
                str(ROOT / "scripts" / "lib"),
            ],
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": os.environ.get("PATH", "")},
        )

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
