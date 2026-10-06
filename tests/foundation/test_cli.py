from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.play.cli import FIELD_GUIDE, main
from scripts.lib.play.rote_ownership import rote_managed_play


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bin" / "play"


class PlayCliTest(unittest.TestCase):
    def test_help_is_a_themed_index_of_agent_and_shell_operations(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for heading in (
            "AGENT · DISCOVER AND RUN",
            "EXPLORE & VISUALIZE",
            "RECALL & REFERENCE",
            "RECURRING PLAYS · OPTIONAL TULVING",
            "ROUTING",
            "RECOVERY & DIAGNOSTICS",
        ):
            self.assertIn(heading, result.stdout)
        self.assertIn("$play explore <outcome>", result.stdout)
        self.assertIn("play search <outcome>", result.stdout)
        self.assertIn("play journey live", result.stdout)
        self.assertIn("play-journey view --active", result.stdout)
        self.assertIn("play cheat-sheet", result.stdout)
        self.assertIn("play guide [topic]", result.stdout)
        self.assertIn("INSPECT & IMPROVE", result.stdout)
        self.assertIn("play audit <play URI|path>", result.stdout)
        self.assertIn("play audit history <ref>", result.stdout)
        self.assertIn(FIELD_GUIDE, result.stdout)
        self.assertIn("play recurring probe", result.stdout)
        self.assertIn("play recurring list", result.stdout)
        self.assertIn("play recurring recall", result.stdout)
        self.assertIn("play recurring last", result.stdout)
        self.assertIn("play recurring status", result.stdout)
        self.assertIn("play recurring clock on|off", result.stdout)
        self.assertIn("play recurring update", result.stdout)
        self.assertIn("play schedule", result.stdout)
        self.assertIn("play update", result.stdout)
        for journey_operation in (
            "snapshot",
            "graph",
            "story",
            "scene",
            "view",
            "doctor",
            "refresh",
            "rebuild",
            "worker",
        ):
            self.assertIn(journey_operation, result.stdout)

    def test_version_comes_from_the_release_version_file(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"play {(ROOT / 'VERSION').read_text().strip()}\n", result.stdout)

    def test_audit_delegates_to_play_audit_with_its_arguments(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def executor(path: str, argv: list[str]) -> None:
            calls.append((path, argv))

        self.assertEqual(0, main(["audit", "owner/name@1.0.0", "--author"], executor=executor))
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("/play-audit"))
        self.assertEqual(["owner/name@1.0.0", "--author"], calls[0][1][1:])
        self.assertEqual(0, main(["audit"], executor=executor))
        self.assertEqual(["--help"], calls[1][1][1:])

    def test_journey_live_expands_to_the_active_viewer(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["journey", "live", "--no-open", "--port", "4321"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-journey"), executable)
        self.assertEqual(
            [executable, "view", "--active", "--no-open", "--port", "4321"],
            arguments,
        )

    def test_journal_defaults_to_today(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["journal"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-journal"), executable)
        self.assertEqual([executable, "show", "--day", "today"], arguments)

    def test_two_token_whats_new_alias_runs_the_remembered_digest(self) -> None:
        for command in (["what's", "new"], ["whats", "new"]):
            calls: list[tuple[str, list[str]]] = []

            result = main(
                command,
                executor=lambda executable, arguments: calls.append(
                    (executable, arguments)
                ),
            )

            self.assertEqual(0, result)
            executable, arguments = calls.pop()
            self.assertEqual(str(ROOT / "scripts/bin/play-digest"), executable)
            self.assertEqual(
                [executable, "--remember", "--days", "7"], arguments
            )

    def test_schedule_is_an_alias_for_recurring_schedule(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["schedule", "--reference", "modiqo/check@1.2.3"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-recurring"), executable)
        self.assertEqual(
            [executable, "schedule", "--reference", "modiqo/check@1.2.3"],
            arguments,
        )

    def test_guide_delegates_without_preflight_or_identity_recovery(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        identity_calls = []

        result = main(
            ["guide", "run"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: identity_calls.append(True) or False,
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-guide"), executable)
        self.assertEqual([executable, "run"], arguments)
        self.assertEqual([], identity_calls)

    def test_search_delegates_to_the_unified_local_and_registry_search(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["search", "incident", "triage", "--json"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: True,
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-search"), executable)
        self.assertEqual([executable, "incident", "triage", "--json"], arguments)

    def test_search_stops_before_discovery_when_identity_recovery_fails(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["search", "incident", "triage"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: False,
        )

        self.assertEqual(1, result)
        self.assertEqual([], calls)

    def test_update_executes_the_bundled_verified_installer(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        with tempfile.TemporaryDirectory() as home, patch.dict(
            os.environ, {"HOME": home, "ROTE_HOME": str(Path(home) / "rote")}
        ):
            result = main(
                ["update", "--harness", "codex"],
                executor=lambda executable, arguments: calls.append(
                    (executable, arguments)
                ),
            )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                (
                    "/bin/sh",
                    ["/bin/sh", str(ROOT / "install.sh"), "--harness", "codex"],
                )
            ],
            calls,
        )

    def _rote_home_with_play_record(self, base: Path) -> Path:
        rote_home = base / "rote-home"
        (rote_home / "play").mkdir(parents=True)
        (rote_home / "play" / "install.json").write_text("{}", encoding="utf-8")
        return rote_home

    def _fake_rote(self, base: Path) -> Path:
        bin_dir = base / "bin"
        bin_dir.mkdir()
        rote = bin_dir / "rote"
        rote.write_text(
            "#!/bin/sh\nprintf 'rote %s ROTE_HOME=%s\\n' \"$*\" \"${ROTE_HOME:-}\"\n",
            encoding="utf-8",
        )
        rote.chmod(0o755)
        return bin_dir

    def test_update_hands_a_rote_managed_install_to_rote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            rote_home = self._rote_home_with_play_record(base)
            bin_dir = self._fake_rote(base)
            result = subprocess.run(
                [str(SCRIPT), "update"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "HOME": str(base),
                    "ROTE_HOME": str(rote_home),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Play is managed by rote. Running: rote install play", result.stderr)
        self.assertEqual(f"rote install play ROTE_HOME={rote_home}\n", result.stdout)

    def test_update_honors_nonempty_rote_home_over_the_default_home(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            default_record = base / ".rote" / "play" / "install.json"
            default_record.parent.mkdir(parents=True)
            default_record.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ, {"HOME": str(base), "ROTE_HOME": str(base / "elsewhere")}
            ):
                result = main(
                    ["update"],
                    executor=lambda executable, arguments: calls.append(
                        (executable, arguments)
                    ),
                )

        self.assertEqual(0, result)
        self.assertEqual("/bin/sh", calls[0][0])

    def test_update_without_rote_on_path_names_the_record_and_command(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            rote_home = self._rote_home_with_play_record(base)
            with patch.dict(
                os.environ,
                {"HOME": str(base), "ROTE_HOME": str(rote_home), "PATH": str(base)},
            ), patch("sys.stderr") as stderr:
                result = main(
                    ["update"],
                    executor=lambda executable, arguments: calls.append(
                        (executable, arguments)
                    ),
                )
            message = "".join(call.args[0] for call in stderr.write.call_args_list)

        self.assertEqual(1, result)
        self.assertEqual([], calls)
        self.assertIn(str(rote_home / "play" / "install.json"), message)
        self.assertIn("rote install play", message)

    def test_update_rejects_legacy_installer_options_when_rote_manages_play(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            rote_home = self._rote_home_with_play_record(base)
            bin_dir = self._fake_rote(base)
            with patch.dict(
                os.environ,
                {
                    "HOME": str(base),
                    "ROTE_HOME": str(rote_home),
                    "PATH": str(bin_dir),
                },
            ):
                result = main(
                    ["update", "--harness", "codex"],
                    executor=lambda executable, arguments: calls.append(
                        (executable, arguments)
                    ),
                )

        self.assertEqual(2, result)
        self.assertEqual([], calls)

    def test_rote_versions_tree_names_its_own_rote_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rote_home = Path(temporary).resolve() / "sandbox-rote"
            release = rote_home / "play" / "versions" / "0.4.110-0123456789ab"
            release.mkdir(parents=True)
            managed = rote_managed_play(release, {"ROTE_HOME": ""})

        self.assertIsNotNone(managed)
        assert managed is not None
        self.assertEqual(rote_home, managed.rote_home)
        self.assertTrue(managed.rote_home_derived)

    def test_update_help_does_not_download_or_install(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "update", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("play update [installer arguments]", result.stdout)
        self.assertIn("snapshots", result.stdout)

    def test_unknown_command_is_actionable(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "unknown"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("unknown command", result.stderr)
        self.assertIn("play --help", result.stderr)


if __name__ == "__main__":
    unittest.main()
