from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "harness" / "install-all"
PROFILE = ROOT / "scripts" / "harness" / "play-profile"


class InstallAllTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        rote = self.bin / "rote"
        rote.write_text(
            "#!/bin/sh\n"
            "case \"${1:-}\" in\n"
            "  version) echo 'version: 1.0.0' ;;\n"
            "  whoami)\n"
            "    if [ \"${ROTE_TEST_LOGGED_OUT:-}\" = 1 ] && [ ! -f \"${HOME}/.rote-test-logged-in\" ]; then\n"
            "      echo 'error: Not logged in'\n"
            "      exit 1\n"
            "    fi\n"
            "    echo 'ok: person@example.com'\n"
            "    ;;\n"
            "  login)\n"
            "    : > \"${HOME}/.rote-test-logged-in\"\n"
            "    echo 'browser sign-in completed'\n"
            "    ;;\n"
            "  self-update)\n"
            "    if [ \"${2:-}\" = '--check' ]; then\n"
            "      echo 'You are on the latest version!'\n"
            "    else\n"
            "      echo 'unexpected Rote update' >&2\n"
            "      exit 41\n"
            "    fi\n"
            "    ;;\n"
            "  install) echo 'Rote skills installed' ;;\n"
            "  registry)\n"
            "    if [ \"${2:-}\" = org ] && [ \"${3:-}\" = list ]; then\n"
            "      echo '[]'\n"
            "    fi\n"
            "    ;;\n"
            "  play) echo 'rote play' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        rote.chmod(0o755)
        self.roots = {
            "codex": self.home / ".codex" / "skills",
            "claude": self.home / ".claude" / "skills",
            "kimi": self.home / ".agents" / "skills",
        }
        for name, root in self.roots.items():
            skill = root / ("rote" if name != "claude" else "rote-shell")
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {skill.name}\ndescription: test\n---\n",
                encoding="utf-8",
            )
            command = self.bin / name
            if name == "codex":
                command.write_text(
                    "#!/bin/sh\n"
                    "marker=\"${CODEX_HOME}/play-plugin-installed\"\n"
                    "if [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = marketplace ] && [ \"${3:-}\" = list ]; then\n"
                    "  printf '%s\\n' '{\"marketplaces\":[]}'\n"
                    "elif [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = list ]; then\n"
                    "  if [ -f \"$marker\" ]; then\n"
                    "    printf '%s\\n' '{\"installed\":[{\"pluginId\":\"play@play-skills\",\"version\":\"0.4.33\",\"enabled\":true}],\"available\":[]}'\n"
                    "  else\n"
                    "    printf '%s\\n' '{\"installed\":[],\"available\":[]}'\n"
                    "  fi\n"
                    "elif [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = add ]; then\n"
                    "  : > \"$marker\"\n"
                    "fi\n",
                    encoding="utf-8",
                )
            elif name == "claude":
                command.write_text(
                    "#!/bin/sh\n"
                    "marker=\"${CLAUDE_CONFIG_DIR}/play-plugin-installed\"\n"
                    "if [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = marketplace ] && [ \"${3:-}\" = list ]; then\n"
                    "  printf '%s\\n' '[]'\n"
                    "elif [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = list ]; then\n"
                    "  if [ -f \"$marker\" ]; then\n"
                    "    printf '%s\\n' '[{\"id\":\"play@play-skills\",\"version\":\"0.4.33\",\"enabled\":true,\"scope\":\"user\"}]'\n"
                    "  else\n"
                    "    printf '%s\\n' '[]'\n"
                    "  fi\n"
                    "elif [ \"${1:-}\" = plugin ] && [ \"${2:-}\" = install ]; then\n"
                    "  : > \"$marker\"\n"
                    "fi\n",
                    encoding="utf-8",
                )
            else:
                command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command.chmod(0o755)

        self.state = self.home / "state" / "activation.json"
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "PATH": os.pathsep.join(
                    (str(self.bin), str(Path(sys.executable).parent), "/usr/bin", "/bin")
                ),
                "CODEX_HOME": str(self.home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "KIMI_CONFIG_DIR": str(self.home / ".kimi"),
                "HERMES_HOME": str(self.home / ".hermes"),
                "OPENCODE_CONFIG_DIR": str(self.home / ".config" / "opencode"),
                "DSH_HOME": str(self.home / ".dsh"),
                "AGENTS_HOME": str(self.home / ".agents"),
                "PLAY_HARNESS_ROOTS": os.pathsep.join(
                    str(path) for path in self.roots.values()
                ),
                "PLAY_PROFILE_STATE": str(self.state),
                "PLAY_BOOTSTRAP_STATE": str(self.home / "bootstrap-state"),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(
        self, *arguments: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(INSTALLER), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(expected, result.returncode, result.stderr)
        return result

    def uninstall(self, source: Path) -> None:
        environment = {**self.environment, "PLAY_PROFILE_SOURCE": str(source)}
        subprocess.run(
            [str(source / "scripts" / "harness" / "play-profile"), "uninstall"],
            cwd=source,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_source_install_detects_and_verifies_every_harness(self) -> None:
        result = self.run_installer("install")

        self.assertIn("Detected harnesses: codex, claude, kimi", result.stdout)
        for name, root in self.roots.items():
            play = root / "play"
            self.assertTrue(play.is_symlink(), name)
            self.assertEqual(ROOT, play.resolve())

        launcher = self.home / ".local" / "bin" / "play-machine"
        self.assertTrue(launcher.is_file())
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn(str(ROOT / "scripts" / "bin" / "play-machine"), launcher.read_text())
        routing_launcher = self.home / ".local" / "bin" / "play-routing"
        self.assertTrue(routing_launcher.is_file())
        self.assertTrue(os.access(routing_launcher, os.X_OK))
        self.assertIn(
            str(ROOT / "scripts" / "bin" / "play-routing"),
            routing_launcher.read_text(),
        )
        routing = self.home / ".rote-play" / "routing.yaml"
        self.assertTrue(routing.is_file())
        self.assertEqual(
            {"schema": "play.routing/v1", "routes": []},
            yaml.safe_load(routing.read_text()),
        )
        self.assertEqual(0o600, routing.stat().st_mode & 0o777)
        journals = self.home / ".rote-play" / "journal-settings.json"
        self.assertTrue(journals.is_file())
        journal_settings = json.loads(journals.read_text())
        self.assertTrue(journal_settings["enabled"])
        self.assertEqual(5, journal_settings["exploration"]["interval_steps"])
        self.assertTrue(journal_settings["recall"]["enabled"])
        self.assertEqual(0o600, journals.stat().st_mode & 0o777)

        self.run_installer("verify")
        self.uninstall(ROOT)
        self.assertFalse(launcher.exists())
        self.assertFalse(routing_launcher.exists())

    def test_targets_exposes_multi_select_vendor_choices(self) -> None:
        result = self.run_installer("targets", "--json")
        payload = json.loads(result.stdout)

        self.assertEqual("play.install-targets/v1", payload["schema"])
        self.assertEqual("multiple", payload["selection"])
        self.assertEqual(
            [
                "codex",
                "claude",
                "kimi",
                "cursor",
                "hermes",
                "opencode",
                "deepseek",
            ],
            [target["id"] for target in payload["targets"]],
        )
        codex = payload["targets"][0]
        self.assertTrue(codex["selected"])
        self.assertTrue(codex["rote_skills_installed"])

    def test_repeated_harness_flags_install_only_selected_roots(self) -> None:
        result = self.run_installer(
            "install", "--harness", "codex", "--harness", "kimi"
        )

        self.assertIn("Detected harnesses: codex, kimi", result.stdout)
        self.assertTrue((self.roots["codex"] / "play").is_symlink())
        self.assertTrue((self.roots["kimi"] / "play").is_symlink())
        self.assertFalse((self.roots["claude"] / "play").exists())
        self.assertIn("Python launcher", result.stdout)
        self.uninstall(ROOT)

    def test_install_backs_up_then_overwrites_existing_play_owned_paths(self) -> None:
        old_play = self.roots["codex"] / "play"
        old_play.mkdir()
        (old_play / "SKILL.md").write_text("old play\n", encoding="utf-8")
        old_launcher = self.home / ".local" / "bin" / "play-machine"
        old_launcher.parent.mkdir(parents=True)
        old_launcher.write_text("old launcher\n", encoding="utf-8")

        result = self.run_installer("install", "--harness", "codex")

        self.assertIn("Play state backup:", result.stdout)
        self.assertTrue(old_play.is_symlink())
        self.assertEqual(ROOT, old_play.resolve())
        manifests = list(
            (self.home / "bootstrap-state" / "backups").glob(
                "install-all-*/manifest.json"
            )
        )
        self.assertEqual(1, len(manifests))
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        self.assertIn(str(old_play), entries)
        self.assertIn(str(old_launcher), entries)
        backed_play = manifests[0].parent / entries[str(old_play)]["backup"]
        backed_launcher = manifests[0].parent / entries[str(old_launcher)]["backup"]
        self.assertEqual("old play\n", (backed_play / "SKILL.md").read_text())
        self.assertEqual("old launcher\n", backed_launcher.read_text())
        self.uninstall(ROOT)

    def test_opencode_install_adds_managed_slash_command_and_preserves_conflict(self) -> None:
        skill_root = self.home / ".config" / "opencode" / "skills"
        rote = skill_root / "rote"
        rote.mkdir(parents=True)
        (rote / "SKILL.md").write_text("---\nname: rote\n---\n", encoding="utf-8")
        command = self.bin / "opencode"
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)
        play_command = self.home / ".config" / "opencode" / "commands" / "play.md"
        play_command.parent.mkdir(parents=True)
        play_command.write_text("my existing command\n", encoding="utf-8")

        result = self.run_installer("install", "--harness", "opencode")

        self.assertIn("opencode command backup", result.stdout)
        self.assertTrue((skill_root / "play").is_symlink())
        self.assertIn("managed-by: modiqo/play", play_command.read_text(encoding="utf-8"))
        self.assertEqual(
            "my existing command\n",
            play_command.with_name("play.md.pre-play-backup").read_text(encoding="utf-8"),
        )
        self.run_installer("verify", "--harness", "opencode")
        self.uninstall(ROOT)

    def test_portable_copy_is_stable_and_idempotent(self) -> None:
        install_home = self.home / "portable"
        self.environment["PLAY_INSTALL_HOME"] = str(install_home)

        self.run_installer("install", "--copy")
        installed = install_home / "skill"
        self.assertEqual("0.4.33", (installed / "VERSION").read_text().strip())
        marker = json.loads((installed / ".play-install.json").read_text())
        self.assertEqual("play.portable-install/v1", marker["schema"])
        for root in self.roots.values():
            self.assertEqual(installed.resolve(), (root / "play").resolve())

        result = self.run_installer("install", "--copy")
        self.assertIn("already active", result.stdout)
        self.uninstall(installed)

    def test_portable_copy_migrates_source_profile_with_backup(self) -> None:
        self.run_installer("install")
        previous_state = self.state.read_bytes()
        install_home = self.home / "portable-migration"
        self.environment["PLAY_INSTALL_HOME"] = str(install_home)

        result = self.run_installer("install", "--copy")

        self.assertIn("backed up previous activation profile", result.stdout)
        installed = install_home / "skill"
        migrated = json.loads(self.state.read_text())
        self.assertEqual(str(installed.resolve()), migrated["source"])
        backup = Path(migrated["profile_backups"][0]["path"])
        self.assertEqual(previous_state, backup.read_bytes())
        for root in self.roots.values():
            self.assertEqual(installed.resolve(), (root / "play").resolve())
        self.uninstall(installed)
        self.assertTrue(backup.is_file())

    def test_missing_rote_provider_fails_before_writing(self) -> None:
        missing = self.roots["claude"] / "rote-shell"
        (missing / "SKILL.md").unlink()

        result = self.run_installer("install", expected=1)

        self.assertIn("Rote skill provider is missing", result.stderr)
        self.assertFalse(self.state.exists())
        for root in self.roots.values():
            self.assertFalse((root / "play").exists())

    def test_local_bootstrap_exercises_portable_install(self) -> None:
        install_home = self.home / "curl-portable"
        environment = {
            **self.environment,
            "PLAY_INSTALL_HOME": str(install_home),
            "PLAY_INSTALL_SOURCE": str(ROOT),
            "PLAY_INSTALL_YES": "1",
        }
        started = time.perf_counter()
        result = subprocess.run(
            ["/bin/sh", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertLess(elapsed, 5.0, f"warm three-harness install took {elapsed:.3f}s")
        self.assertIn("Modiqo Rote", result.stdout)
        self.assertIn("Where useful interactions become Plays", result.stdout)
        self.assertIn("Play setup plan", result.stdout)
        self.assertIn("✓ Using local Play source", result.stdout)
        self.assertIn("◐ Checking the Play setup plan", result.stderr)
        self.assertIn("✓ Verifying Codex", result.stderr)
        self.assertIn("| Play setup plan", result.stdout)
        self.assertIn("Version: 0.4.33", result.stdout)
        self.assertIn("| Play setup", result.stdout)
        self.assertIn("Status: READY", result.stdout)
        self.assertIn("Congratulations — step 1", result.stdout)
        self.assertIn("becoming a Playmaster", result.stdout)
        self.assertIn("mind-meld with your agent of choice", result.stdout)
        self.assertIn('Codex: codex "\\$play what\'s new"', result.stdout)
        self.assertIn('Claude Code: claude "/play what\'s new"', result.stdout)
        installed = install_home / "skill"
        self.assertTrue((installed / "SKILL.md").is_file())
        reports = list((self.home / "bootstrap-state" / "runs").glob("*.json"))
        self.assertEqual(1, len(reports))
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual("completed", report["status"])
        self.assertEqual(["codex", "claude", "kimi"], report["selected_harnesses"])
        step_ids = [step["id"] for step in report["steps"]]
        self.assertLess(step_ids.index("rote_identity"), step_ids.index("backup_play_state"))
        self.assertLess(
            step_ids.index("warm_public_play_cache"),
            step_ids.index("backup_play_state"),
        )
        cache = next(
            step for step in report["steps"] if step["id"] == "warm_public_play_cache"
        )
        self.assertEqual("completed", cache["status"])
        self.assertIn("snapshot sha256:", cache["detail"])
        self.uninstall(installed)

    def test_portable_installer_is_valid_posix_shell(self) -> None:
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        result = subprocess.run(
            ["/bin/sh", "-n", str(ROOT / "install.sh")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('install "$@" < /dev/tty', installer)

    def test_portable_installer_rejects_unknown_login_provider(self) -> None:
        environment = {
            **self.environment,
            "PLAY_INSTALL_SOURCE": str(ROOT),
            "PLAY_INSTALL_YES": "1",
            "PLAY_LOGIN_PROVIDER": "password",
        }

        result = subprocess.run(
            ["/bin/sh", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("PLAY_LOGIN_PROVIDER must be google or github", result.stderr)

    def test_remote_archive_extraction_selects_a_safe_python_policy(self) -> None:
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        start_marker = "python3 - \"$archive\" \"$source_root\" <<'PY'\n"
        extraction = installer.split(start_marker, 1)[1].split("\nPY\n", 1)[0]
        source = self.home / "archive-source"
        source.mkdir()
        (source / "VERSION").write_text("test\n", encoding="utf-8")
        archive = self.home / "play.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source, arcname="play-main")
        destination = self.home / "extracted"

        result = subprocess.run(
            [
                sys.executable,
                "-W",
                "error::DeprecationWarning",
                "-",
                str(archive),
                str(destination),
            ],
            input=extraction,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("test", (destination / "VERSION").read_text().strip())

    def test_local_bootstrap_guides_first_time_sign_in_without_error_state(self) -> None:
        install_home = self.home / "curl-first-use"
        environment = {
            **self.environment,
            "PLAY_INSTALL_HOME": str(install_home),
            "PLAY_INSTALL_SOURCE": str(ROOT),
            "PLAY_INSTALL_YES": "1",
            "ROTE_TEST_LOGGED_OUT": "1",
        }

        result = subprocess.run(
            ["/bin/sh", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertIn("Status: SETUP PAUSED — SIGN IN REQUIRED", result.stdout)
        self.assertIn("Sign in to finish setup", result.stdout)
        self.assertIn("choose Google or GitHub", result.stdout)
        self.assertIn("Play-owned harness state has not been changed", result.stdout)
        self.assertNotIn("rote login --provider", result.stdout)
        self.assertNotIn("Status: INCOMPLETE", result.stdout)
        reports = list((self.home / "bootstrap-state" / "runs").glob("*.json"))
        self.assertEqual(1, len(reports))
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual("onboarding_required", report["status"])
        identity = next(step for step in report["steps"] if step["id"] == "rote_identity")
        self.assertEqual("onboarding_required", identity["status"])
        self.assertFalse((install_home / "skill").exists())

    def test_sign_in_and_disabled_codex_are_actionable_not_install_errors(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.write_text(
            '[[skills.config]]\nname = "play"\nenabled = false\n',
            encoding="utf-8",
        )
        install_home = self.home / "curl-first-use-disabled"
        environment = {
            **self.environment,
            "PLAY_INSTALL_HOME": str(install_home),
            "PLAY_INSTALL_SOURCE": str(ROOT),
            "PLAY_INSTALL_YES": "1",
            "PLAY_LOGIN_PROVIDER": "github",
            "ROTE_TEST_LOGGED_OUT": "1",
        }

        result = subprocess.run(
            ["/bin/sh", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertIn("Status: READY", result.stdout)
        self.assertNotIn("Sign in to finish setup", result.stdout)
        self.assertNotIn("explicit disabled Play skill override", result.stdout)
        self.assertNotIn("[[skills.config]]", config.read_text(encoding="utf-8"))
        self.assertNotIn("Status: INCOMPLETE", result.stdout)
        self.uninstall(install_home / "skill")


if __name__ == "__main__":
    unittest.main()
