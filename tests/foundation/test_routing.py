from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.routing import (
    RoutingError,
    active_routes,
    add_route,
    find_project_policy,
    initialize,
    is_routing_management_request,
    load_policy,
    matching_direct_route,
    remove_route,
)


class RoutingPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.user_policy = self.base / "state" / "routing.yaml"
        self.saved_user_path = os.environ.get("PLAY_ROUTING_USER_PATH")
        os.environ["PLAY_ROUTING_USER_PATH"] = str(self.user_policy)

    def tearDown(self) -> None:
        if self.saved_user_path is None:
            os.environ.pop("PLAY_ROUTING_USER_PATH", None)
        else:
            os.environ["PLAY_ROUTING_USER_PATH"] = self.saved_user_path
        self.temporary.cleanup()

    def test_init_add_update_remove_round_trip(self) -> None:
        policy = self.base / "project" / ".play" / "routing.yaml"
        self.assertTrue(initialize(policy))
        self.assertFalse(initialize(policy))
        self.assertEqual(
            "added",
            add_route(
                policy,
                route_id="github-direct",
                providers=["github", "github-actions"],
                tools=["git", "gh"],
            ),
        )
        self.assertEqual(
            "updated",
            add_route(
                policy,
                route_id="github-direct",
                providers=["github"],
                tools=["gh"],
                executors=["cli"],
            ),
        )
        route = load_policy(policy)["routes"][0]
        self.assertEqual(["github"], route["providers"])
        self.assertEqual(["gh"], route["tools"])
        self.assertEqual(["cli"], route["executors"])

        remove_route(policy, "github-direct")
        self.assertEqual([], load_policy(policy)["routes"])
        with self.assertRaisesRegex(RoutingError, "no route named"):
            remove_route(policy, "github-direct")

    def test_user_policy_is_owner_private(self) -> None:
        self.assertTrue(initialize(self.user_policy, private=True))
        self.assertEqual(0o600, self.user_policy.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.user_policy.parent.stat().st_mode & 0o777)

    def test_nearest_project_policy_is_found_without_crossing_repo_root(self) -> None:
        project = self.base / "project"
        nested = project / "src" / "package"
        nested.mkdir(parents=True)
        (project / ".git").mkdir()
        policy = project / ".play" / "routing.yaml"
        initialize(policy)

        self.assertEqual(policy.resolve(), find_project_policy(nested))

    def test_user_and_project_direct_routes_are_combined(self) -> None:
        initialize(self.user_policy, private=True)
        add_route(
            self.user_policy,
            route_id="cloudflare-direct",
            providers=["cloudflare"],
            tools=["wrangler"],
            private=True,
        )
        project = self.base / "project"
        project.mkdir()
        (project / ".git").mkdir()
        project_policy = project / ".play" / "routing.yaml"
        add_route(
            project_policy,
            route_id="github-direct",
            providers=["github", "github-actions"],
            tools=["git", "gh"],
        )

        self.assertEqual(2, len(active_routes(project)))
        github = matching_direct_route("list github repositories", project_path=project)
        cloudflare = matching_direct_route("deploy with wrangler", project_path=project)
        self.assertEqual("github-direct", github["id"] if github else None)
        self.assertEqual("cloudflare-direct", cloudflare["id"] if cloudflare else None)

    def test_malformed_policy_cannot_authorize_direct_routing(self) -> None:
        self.user_policy.parent.mkdir(parents=True)
        self.user_policy.write_text("schema: wrong\nroutes: []\n", encoding="utf-8")
        self.assertEqual([], active_routes(self.base))
        with self.assertRaisesRegex(RoutingError, "schema must be"):
            load_policy(self.user_policy)

    def test_init_preserves_an_existing_policy_even_when_it_is_malformed(self) -> None:
        self.user_policy.parent.mkdir(parents=True)
        existing = "schema: future.routing/v2\nroutes: []\n"
        self.user_policy.write_text(existing, encoding="utf-8")

        self.assertFalse(initialize(self.user_policy, private=True))
        self.assertEqual(existing, self.user_policy.read_text(encoding="utf-8"))

    def test_repository_default_policy_is_valid(self) -> None:
        policy = load_policy(ROOT / ".play" / "routing.yaml")
        self.assertEqual(["github-direct", "cloudflare-direct"], [
            route["id"] for route in policy["routes"]
        ])

    def test_routing_management_prompts_are_narrow_and_action_shaped(self) -> None:
        accepted = (
            "Initialize Play routing for this repo",
            "set up Play routing",
            "route GitHub directly through gh in this project",
            "show this project's Play routing policy",
            "remove GitHub from the Play direct route here",
            "inspect .play/routing.yaml",
        )
        rejected = (
            "should we route GitHub directly",
            "do we have a skill for Play routing",
            "deploy with Cloudflare",
            "list my GitHub repositories",
            "explain the network routing policy",
        )

        for prompt in accepted:
            with self.subTest(prompt=prompt):
                self.assertTrue(is_routing_management_request(prompt))
        for prompt in rejected:
            with self.subTest(prompt=prompt):
                self.assertFalse(is_routing_management_request(prompt))

    def test_python_cli_add_list_and_remove(self) -> None:
        project = self.base / "cli-project"
        command = ROOT / "scripts" / "bin" / "play-routing"

        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            result = subprocess.run(
                [sys.executable, str(command), "--project", str(project), *arguments],
                cwd=ROOT,
                env={**os.environ, "PLAY_ROUTING_USER_PATH": str(self.user_policy)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return result

        run("init")
        run(
            "add",
            "github-direct",
            "--provider",
            "github",
            "--tool",
            "gh",
            "--executor",
            "cli",
        )
        listed = run("list", "--json")
        self.assertEqual("github-direct", json.loads(listed.stdout)["routes"][0]["id"])
        run("remove", "github-direct")
        self.assertEqual([], load_policy(project / ".play" / "routing.yaml")["routes"])


if __name__ == "__main__":
    unittest.main()
