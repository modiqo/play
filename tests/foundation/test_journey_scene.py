from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts.lib.play.journey import (
    _workspace_fingerprint,
    _persist_graph_state,
    _snapshot_path,
    active_capture_reference,
    build_graph,
    materialize_snapshot,
)
from scripts.lib.play.journey_scene import SCHEMA, build_scene
from scripts.lib.play.journey_story import SCHEMA as STORY_SCHEMA, build_story
from scripts.lib.play.journey_tutorial import (
    TUTORIAL_REFERENCE,
    TUTORIAL_WORKSPACE_ID,
    ensure_tutorial,
    tutorial_exchange,
    tutorial_payload,
)
from scripts.lib.play.journey_view import (
    DEFAULT_VIEWER_PORT,
    EXCHANGE_SCHEMA,
    INTERACTIONS_SCHEMA,
    MAX_LIFETIME_SECONDS,
    _ensure_graph_ready,
    _exchange_projection,
    _interaction_projection,
    _journey_server_pids,
    _journey_server_pids_from_process_list,
    _refresh_workspace_catalog,
    _viewer_state_path,
    _viewer_session_path,
    _viewer_session_token,
    _wait_for_viewer_port,
    _workspace_activity,
    _workspace_catalog,
    _workspace_index,
    make_server,
)
from scripts.lib.play.journey_view_catalog import _active_workspace_capture, _journey_mode
from scripts.lib.play.private_store import atomic_write_json


ROOT = Path(__file__).resolve().parents[2]


def activity(sequence: int, kind: str, *, provider: str | None = None) -> dict:
    return {
        "sequence": sequence,
        "command_type": "Synthetic",
        "response_refs": [f"@{sequence}"],
        "operation": f"{kind}-{sequence}",
        "provider": provider,
        "kind": kind,
        "role": "verification" if kind == "evidence" else None,
        "effect": "read" if kind == "effect" else None,
        "status": "succeeded",
        "duration_ms": sequence * 2,
        "tokens": sequence * 3,
        "tokens_saved": sequence,
        "signature": f"sig-{sequence}",
        "timestamp": None,
    }


class JourneySceneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.journeys = Path(self.temporary.name) / "journeys"
        self.capture = {
            "reference": "cap_scene-test",
            "intent": "Retrieve daily active users",
            "status": "active",
            "trajectory_ref": None,
        }
        self.activities = [
            activity(1, "decision"),
            activity(2, "capability", provider="posthog"),
            activity(3, "authority", provider="posthog"),
            activity(4, "effect", provider="posthog"),
            activity(5, "evidence"),
            activity(6, "milestone"),
            activity(7, "play_candidate"),
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def graph(self, activities: list[dict]) -> dict:
        return build_graph(
            self.capture,
            activities=activities,
            dependencies=[],
            stats={"commands": len(activities), "responses": len(activities)},
        )

    def test_start_here_is_a_deterministic_recorded_workspace(self) -> None:
        graph = ensure_tutorial(root=self.journeys)
        story = build_story(graph)
        scene = build_scene(graph)
        index = _workspace_index(TUTORIAL_REFERENCE, root=self.journeys)

        self.assertEqual("tutorial", graph["origin"]["kind"])
        self.assertEqual("tutorial", graph["route"]["mode"])
        self.assertEqual(
            {"call", "shell", "drive"},
            {item["modality"] for item in graph["capabilities"]},
        )
        self.assertTrue({"blocker", "recovery"}.issubset({item["kind"] for item in graph["nodes"]}))
        shell_station = next(
            chapter["order"]
            for chapter in story["chapters"]
            if chapter["kind"] == "capability" and "shell" in chapter["modalities"]
        )
        shell_operation = next(
            chapter["order"]
            for chapter in story["chapters"]
            if chapter["kind"] == "phase" and "shell" in chapter["modalities"]
        )
        self.assertLess(shell_station, shell_operation)
        self.assertEqual(TUTORIAL_WORKSPACE_ID, index["selected_id"])
        tutorial = tutorial_payload()
        self.assertEqual("start-here-v4", tutorial["version"])
        self.assertEqual(
            list(range(len(story["chapters"]))),
            [cue["chapter"] for cue in tutorial["cues"]],
        )
        decision = next(item for item in story["chapters"] if item["kind"] == "decision")
        self.assertEqual("Choose Notion access route", decision["title"])
        exchange = tutorial_exchange(2)
        self.assertIsNotNone(exchange)
        assert exchange is not None
        self.assertEqual(2, exchange["sequence"])
        failed_exchange = tutorial_exchange(5)
        assert failed_exchange is not None
        self.assertFalse(failed_exchange["response"]["ok"])
        with patch(
            "scripts.lib.play.journey_view_evidence.telemetry_context",
            return_value={"model": {"name": "codex"}},
        ) as telemetry:
            interactions = _interaction_projection(TUTORIAL_REFERENCE, root=self.journeys)
        telemetry.assert_called_once()
        self.assertEqual("codex", interactions["model_telemetry"]["model"]["name"])
        projected = [
            item
            for site in interactions["sites"].values()
            for item in site
        ]
        self.assertEqual(
            sum(item["tokens"] for item in projected),
            sum(item["input_tokens"] + item["output_tokens"] for item in projected),
        )
        for filename, value in (
            ("journey-graph.schema.json", graph),
            ("journey-story.schema.json", story),
            ("journey-scene.schema.json", scene),
        ):
            schema = json.loads((ROOT / "references/explore" / filename).read_text())
            Draft202012Validator(schema).validate(value)

    def test_workspace_activity_uses_bounded_rote_heartbeat_files(self) -> None:
        workspace = Path(self.temporary.name) / "activity-workspace"
        database = workspace / ".rote" / "workspace.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"")
        with patch("scripts.lib.play.journey_view.time.time", return_value=1000.0):
            # Use an explicit historical timestamp so the threshold is deterministic.
            import os

            os.utime(database, (980.0, 980.0))
            activity_epoch, active_recently = _workspace_activity(workspace)
            self.assertEqual(980.0, activity_epoch)
            self.assertTrue(active_recently)
            os.utime(database, (900.0, 900.0))
            activity_epoch, active_recently = _workspace_activity(workspace)
            self.assertEqual(900.0, activity_epoch)
            self.assertFalse(active_recently)

    def test_empty_sqlite_wal_is_not_workspace_activity(self) -> None:
        workspace = Path(self.temporary.name) / "quiet-workspace"
        rote = workspace / ".rote"
        rote.mkdir(parents=True)
        database = rote / "workspace.db"
        marker = rote / "workspace.marker"
        wal = rote / "workspace.db-wal"
        database.write_bytes(b"database")
        marker.write_text("quiet", encoding="utf-8")
        wal.write_bytes(b"")

        import os

        os.utime(database, (1900.0, 1900.0))
        os.utime(marker, (1900.0, 1900.0))
        first = _workspace_fingerprint(workspace)
        os.utime(wal, (2000.0, 2000.0))
        second = _workspace_fingerprint(workspace)
        with patch("scripts.lib.play.journey_view.time.time", return_value=2010.0):
            _activity_epoch, active_recently = _workspace_activity(workspace)

        self.assertEqual(first, second)
        self.assertFalse(active_recently)

        wal.write_bytes(b"new command")
        self.assertNotEqual(first, _workspace_fingerprint(workspace))

    def test_viewer_uses_one_state_file_and_strictly_matches_only_serve_processes(self) -> None:
        self.assertEqual(
            _viewer_state_path("capture-a", root=self.journeys),
            _viewer_state_path("capture-b", root=self.journeys),
        )
        self.assertEqual(DEFAULT_VIEWER_PORT, 52050)
        self.assertGreaterEqual(MAX_LIFETIME_SECONDS, 30 * 24 * 60 * 60)
        processes = """
        101 /usr/bin/python /opt/play-journey serve --capture x --viewer-token secret --port 52050
        102 /usr/bin/python /opt/play-journey view --active
        103 /usr/bin/python unrelated-server --viewer-token secret
        """
        self.assertEqual({101}, _journey_server_pids_from_process_list(processes))

    def test_viewer_session_token_is_private_and_stable_across_restarts(self) -> None:
        first = _viewer_session_token(root=self.journeys)
        second = _viewer_session_token(root=self.journeys)

        self.assertEqual(first, second)
        self.assertEqual(0o600, _viewer_session_path(root=self.journeys).stat().st_mode & 0o777)

    def test_viewer_session_migrates_the_running_viewer_token(self) -> None:
        atomic_write_json(
            _viewer_state_path("capture-a", root=self.journeys),
            {
                "schema": "play.journey-viewer/v1",
                "url": "http://127.0.0.1:52050/?token=existing-viewer-token-1234",
            },
        )

        self.assertEqual(
            "existing-viewer-token-1234",
            _viewer_session_token(root=self.journeys),
        )

    def test_viewer_waits_for_the_singleton_port_to_be_released(self) -> None:
        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        port = int(held.getsockname()[1])
        try:
            self.assertFalse(_wait_for_viewer_port(port, timeout_seconds=0.01))
        finally:
            held.close()
        self.assertTrue(_wait_for_viewer_port(port, timeout_seconds=0.01))

    def test_viewer_shutdown_falls_back_to_owner_private_state_pid(self) -> None:
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.wait, timeout=1.0)
        self.addCleanup(sleeper.kill)
        atomic_write_json(
            _viewer_state_path("capture-a", root=self.journeys),
            {
                "schema": "play.journey-viewer/v1",
                "pid": sleeper.pid,
                "port": DEFAULT_VIEWER_PORT,
                "asset_sha256": "sha256:test",
            },
        )
        empty_process_list = subprocess.CompletedProcess(
            args=["ps"], returncode=0, stdout="", stderr=""
        )

        with (
            patch(
                "scripts.lib.play.journey_view.subprocess.run",
                return_value=empty_process_list,
            ),
            patch(
                "scripts.lib.play.journey_view._viewer_state_serves_expected_assets",
                return_value=True,
            ),
        ):
            self.assertEqual({sleeper.pid}, _journey_server_pids(root=self.journeys))

    def test_journey_mode_distinguishes_growing_captures_from_recordings(self) -> None:
        self.assertEqual("live", _journey_mode("active"))
        self.assertEqual("recorded", _journey_mode("completed"))
        self.assertEqual("recorded", _journey_mode("blocked"))

    def test_active_capture_requires_a_present_rote_workspace(self) -> None:
        standby = Path(self.temporary.name) / "standby-active.json"
        missing = Path(self.temporary.name) / "missing-workspace"
        present = Path(self.temporary.name) / "present-workspace"
        database = present / ".rote" / "workspace.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"workspace")
        atomic_write_json(
            standby,
            {
                "captures": [
                    {"reference": "cap-present", "status": "active", "workspace_path": str(present)},
                    {"reference": "cap-stale", "status": "active", "workspace_path": str(missing)},
                ]
            },
        )
        self.assertEqual("cap-present", active_capture_reference(standby_path=standby))

    def test_active_workspace_sync_prefers_cwd_then_latest_rote_workspace(self) -> None:
        rote_home = Path(self.temporary.name) / "rote-active-home"
        workspaces = rote_home / "workspaces"
        captured = workspaces / "play-capture-existing"
        latest = workspaces / "independent-exploration"
        for modified, workspace in ((100.0, captured), (50.0, latest)):
            database = workspace / ".rote" / "workspace.db"
            database.parent.mkdir(parents=True)
            database.write_bytes(b"workspace")
            os.utime(database, (modified, modified))
        latest_wal = latest / ".rote" / "workspace.db-wal"
        latest_wal.write_bytes(b"active command")
        os.utime(latest_wal, (200.0, 200.0))
        standby = Path(self.temporary.name) / "standby-sync.json"
        registered = {
            "reference": "cap-existing",
            "intent": "Existing capture",
            "status": "active",
            "workspace": captured.name,
            "workspace_path": str(captured),
        }
        atomic_write_json(standby, {"captures": [registered], "hooks": []})
        environment = {
            "ROTE_HOME": str(rote_home),
            "PLAY_SIDEKICK_STANDBY_PATH": str(standby),
        }
        with patch.dict(os.environ, environment, clear=False):
            attached = _active_workspace_capture(cwd=Path(self.temporary.name))
            from_cwd = _active_workspace_capture(cwd=captured / "nested")
            assert attached is not None
            summaries, _lookup = _workspace_catalog(
                str(attached["reference"]), root=self.journeys
            )

        self.assertEqual(latest.name, attached["workspace"])
        self.assertEqual("active", attached["status"])
        self.assertTrue(str(attached["reference"]).startswith("workspace:"))
        self.assertEqual(registered, from_cwd)
        latest_summary = next(item for item in summaries if item["workspace"] == latest.name)
        self.assertEqual("live", latest_summary["journey_mode"])
        self.assertFalse(latest_summary["active_recently"])

    def test_active_workspace_sync_falls_back_to_the_legacy_rote_root(self) -> None:
        rote_home = Path(self.temporary.name) / "rote-legacy-home"
        workspace = rote_home / "rote" / "workspaces" / "legacy-exploration"
        database = workspace / ".rote" / "workspace.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"workspace")

        with patch.dict(os.environ, {"ROTE_HOME": str(rote_home)}, clear=False):
            attached = _active_workspace_capture(cwd=Path(self.temporary.name))

        assert attached is not None
        self.assertEqual(workspace.name, attached["workspace"])
        self.assertEqual(str(workspace), attached["workspace_path"])

    def test_attached_workspace_is_synchronized_before_viewer_launch(self) -> None:
        capture = {
            **self.capture,
            "workspace_path": str(Path(self.temporary.name) / "attached"),
        }
        graph = self.graph(self.activities)
        with patch(
            "scripts.lib.play.journey_view.refresh_capture", return_value={"generation": 1}
        ) as refresh, patch(
            "scripts.lib.play.journey_view.load_graph", return_value=graph
        ):
            _ensure_graph_ready(
                self.capture["reference"],
                capture=capture,
                root=self.journeys,
                timeout_seconds=0.5,
            )

        refresh.assert_called_once_with(capture, root=self.journeys)

    def test_workspace_refresh_aligns_archive_to_current_rote_root(self) -> None:
        rote_home = Path(self.temporary.name) / "rote-home"
        workspaces = rote_home / "workspaces"
        current = workspaces / "play-capture-current"
        untracked = workspaces / "dag-hello"
        internal = workspaces / ".rote-locks"
        for workspace in (current, untracked, internal):
            database = workspace / ".rote" / "workspace.db"
            database.parent.mkdir(parents=True)
            database.write_bytes(b"workspace")
        stale = workspaces / "play-capture-backed-up"
        current_capture = {
            **self.capture,
            "reference": "cap_current",
            "workspace": current.name,
            "workspace_path": str(current),
        }
        stale_capture = {
            **self.capture,
            "reference": "cap_stale",
            "workspace": stale.name,
            "workspace_path": str(stale),
        }
        standby = Path(self.temporary.name) / "standby-refresh.json"
        atomic_write_json(
            standby,
            {"captures": [current_capture, stale_capture], "hooks": []},
        )
        current_graph = build_graph(
            current_capture,
            activities=self.activities,
            dependencies=[],
            stats={"commands": len(self.activities), "responses": len(self.activities)},
        )
        stale_graph = build_graph(
            stale_capture,
            activities=self.activities,
            dependencies=[],
            stats={"commands": len(self.activities), "responses": len(self.activities)},
        )
        for capture, graph in ((current_capture, current_graph), (stale_capture, stale_graph)):
            _persist_graph_state(
                capture["reference"],
                fingerprint="d" * 64,
                command_count=len(self.activities),
                activities=self.activities,
                dependencies=[],
                graph=graph,
                root=self.journeys,
            )

        environment = {
            "ROTE_HOME": str(rote_home),
            "PLAY_SIDEKICK_STANDBY_PATH": str(standby),
        }
        with patch.dict(os.environ, environment, clear=False):
            summaries, lookup = _workspace_catalog("cap_stale", root=self.journeys)
            index = _workspace_index("cap_stale", root=self.journeys)
            with patch(
                "scripts.lib.play.journey_view_catalog.schedule_worker", return_value=True
            ) as schedule, patch(
                "scripts.lib.play.journey_view_catalog._schedule_workspace_projection",
                return_value=True,
            ) as workspace_schedule:
                refreshed = _refresh_workspace_catalog("cap_stale", root=self.journeys)

        self.assertEqual(
            {"start-here", "play-capture-current", "dag-hello"},
            {item["workspace"] for item in summaries},
        )
        self.assertNotIn("cap_stale", lookup.values())
        self.assertNotIn(".rote-locks", {item["workspace"] for item in summaries})
        current_summary = next(item for item in summaries if item["workspace"] == current.name)
        untracked_summary = next(item for item in summaries if item["workspace"] == untracked.name)
        self.assertTrue(current_summary["graph_ready"])
        self.assertEqual("live", current_summary["journey_mode"])
        self.assertTrue(current_summary["projectable"])
        self.assertEqual(str(current), current_summary["workspace_path"])
        self.assertFalse(untracked_summary["graph_ready"])
        self.assertTrue(untracked_summary["projectable"])
        self.assertEqual("workspace", untracked_summary["capture_state"])
        self.assertEqual("workspace", untracked_summary["journey_mode"])
        self.assertEqual(current_summary["id"], index["selected_id"])
        self.assertEqual(1, refreshed["reconciliation"]["stale_captures_hidden"])
        self.assertEqual(2, refreshed["reconciliation"]["current_workspaces"])
        self.assertEqual(1, refreshed["reconciliation"]["mapped_captures"])
        schedule.assert_called_once_with(current_capture)
        workspace_schedule.assert_called_once()

    def test_legacy_interactions_receive_structured_capability_families(self) -> None:
        capture = {**self.capture, "reference": "cap_legacy-capabilities"}
        activities = [
            {
                **activity(1, "capability"),
                "command_type": "ProcessExec",
                "operation": "rg --files",
            },
            {
                **activity(2, "evidence"),
                "command_type": "QueryRead",
                "operation": "query stored evidence",
            },
            {
                **activity(3, "effect", provider="github"),
                "command_type": "HttpRequest",
                "operation": "repos/list-contributors",
            },
        ]
        graph = build_graph(
            capture,
            activities=activities,
            dependencies=[],
            stats={"commands": len(activities), "responses": len(activities)},
        )
        _persist_graph_state(
            capture["reference"],
            fingerprint="e" * 64,
            command_count=len(activities),
            activities=activities,
            dependencies=[],
            graph=graph,
            root=self.journeys,
        )

        projected = _interaction_projection(capture["reference"], root=self.journeys)
        descriptors = {
            item["sequence"]: item["capability"]
            for records in projected["sites"].values()
            for item in records
        }

        self.assertEqual(
            ("proc", "rg"),
            (descriptors[1]["family"], descriptors[1]["id"]),
        )
        self.assertEqual("rote", descriptors[2]["family"])
        # A legacy projection has already discarded the typed adapter endpoint
        # and MCP envelope. A provider display label alone is not sufficient to
        # reconstruct adapter ownership, so the compatibility path refuses to
        # guess.
        self.assertEqual("rote", descriptors[3]["family"])

    def test_recalled_play_runtime_is_telemetry_not_a_site_exchange(self) -> None:
        capture = {
            **self.capture,
            "reference": "cap_recalled-runtime",
            "origin": {"kind": "recalled_play", "exact_reference": "modiqo/example@1.0.0"},
        }
        runtime = {
            **activity(1, "phase"),
            "source": "command_log",
            "command_type": "ProcessExec",
            "operation": "deno eval",
            "capability": {"family": "proc", "interface": "shell", "id": "deno", "label": "deno CLI"},
            "capability_ref": "cap_deno",
            "modality": "shell",
            "lifecycle_phase": "use",
        }
        gmail = {
            **activity(2, "effect", provider="gmail"),
            "source": "typed_response",
            "command_type": "HttpRequest",
            "operation": "gmail.users.messages.list",
            "capability": {"family": "adapter", "interface": "api", "id": "gmail", "label": "Gmail API"},
            "capability_ref": "cap_gmail",
            "modality": "call",
            "lifecycle_phase": "use",
        }
        activities = [runtime, gmail]
        graph = build_graph(
            capture,
            activities=activities,
            dependencies=[],
            stats={"commands": 2, "responses": 2},
        )
        _persist_graph_state(
            capture["reference"],
            fingerprint="a" * 64,
            command_count=2,
            activities=activities,
            dependencies=[],
            graph=graph,
            root=self.journeys,
        )

        projected = _interaction_projection(capture["reference"], root=self.journeys)
        visible_sequences = [
            item["sequence"]
            for records in projected["sites"].values()
            for item in records
        ]
        self.assertEqual([2], visible_sequences)
        self.assertEqual([1], [item["sequence"] for item in projected["runtime"]])
        self.assertEqual("node_intent", projected["runtime"][0]["site_id"])
        self.assertEqual("play_runtime", projected["runtime"][0]["presentation_role"])
        self.assertEqual(1, projected["total"])

    def test_scene_is_complete_deterministic_and_schema_valid(self) -> None:
        graph = self.graph(self.activities)
        first = build_scene(graph)
        second = build_scene(graph)
        schema = json.loads(
            (ROOT / "references/explore/journey-scene.schema.json").read_text()
        )

        Draft202012Validator(schema).validate(first)
        self.assertEqual(SCHEMA, first["schema"])
        self.assertEqual(first, second)
        self.assertEqual(len(graph["nodes"]), len(first["nodes"]))
        self.assertEqual(len(graph["edges"]), len(first["edges"]))
        self.assertEqual(
            {node["id"] for node in graph["nodes"]},
            {node["id"] for node in first["nodes"]},
        )

    def test_existing_coordinates_do_not_move_when_work_is_appended(self) -> None:
        initial = build_scene(self.graph(self.activities[:5]))
        expanded = build_scene(self.graph(self.activities))
        initial_positions = {node["id"]: node["position"] for node in initial["nodes"]}
        expanded_positions = {node["id"]: node["position"] for node in expanded["nodes"]}

        self.assertEqual(
            initial_positions,
            {node_id: expanded_positions[node_id] for node_id in initial_positions},
        )

    def test_semantic_edges_receive_distinct_stable_routes(self) -> None:
        scene = build_scene(self.graph(self.activities))
        semantic = {
            edge["kind"]: edge
            for edge in scene["edges"]
            if edge["kind"] in {
                "selects",
                "authorizes",
                "executes",
                "produces",
                "verifies",
                "crystallizes_into",
            }
        }

        self.assertEqual(
            {
                "selects",
                "authorizes",
                "executes",
                "produces",
                "verifies",
                "crystallizes_into",
            },
            set(semantic),
        )
        self.assertTrue(all(len(edge["route"]) >= 2 for edge in semantic.values()))
        self.assertEqual(
            len({edge["id"] for edge in scene["edges"]}),
            len(scene["edges"]),
        )

    def test_loopback_viewer_serves_only_the_complete_scene_to_an_authorized_client(self) -> None:
        graph = self.graph(self.activities)
        _persist_graph_state(
            self.capture["reference"],
            fingerprint="f" * 64,
            command_count=len(self.activities),
            activities=self.activities,
            dependencies=[],
            graph=graph,
            root=self.journeys,
        )
        atomic_write_json(
            _snapshot_path(self.capture["reference"], root=self.journeys),
            materialize_snapshot(graph),
        )
        server = make_server(
            self.capture["reference"], "viewer-secret", root=self.journeys
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(
                f"{base}/api/scene?token=viewer-secret", timeout=2
            ) as response:
                payload = json.loads(response.read())
                self.assertEqual(SCHEMA, payload["schema"])
                self.assertEqual("no-store", response.headers["Cache-Control"])
                self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
            with urllib.request.urlopen(
                f"{base}/api/story?token=viewer-secret", timeout=2
            ) as response:
                story = json.loads(response.read())
                self.assertEqual(STORY_SCHEMA, story["schema"])
                self.assertEqual(len(graph["nodes"]), story["audit"]["canonical_nodes"])
            with urllib.request.urlopen(
                f"{base}/api/interactions?token=viewer-secret", timeout=2
            ) as response:
                interactions = json.loads(response.read())
                self.assertEqual(INTERACTIONS_SCHEMA, interactions["schema"])
                self.assertEqual(len(self.activities), interactions["total"])
                self.assertIn(
                    "read",
                    {
                        item.get("effect")
                        for items in interactions["sites"].values()
                        for item in items
                    },
                )
                self.assertNotIn("params", json.dumps(interactions))
            with urllib.request.urlopen(
                f"{base}/api/workspaces?token=viewer-secret", timeout=2
            ) as response:
                index = json.loads(response.read())
                self.assertEqual("play.journey-workspace-index/v1", index["schema"])
                selected = next(
                    workspace
                    for workspace in index["workspaces"]
                    if workspace["id"] == index["selected_id"]
                )
                self.assertTrue(selected["graph_ready"])
                self.assertEqual(len(graph["nodes"]), selected["nodes"])
                self.assertIn("activity_epoch", selected)
                self.assertIn("active_recently", selected)
                self.assertNotIn(self.capture["reference"], json.dumps(index))
                project_request = urllib.request.Request(
                    f"{base}/api/project?token=viewer-secret&workspace={selected['id']}",
                    method="POST",
                )
                with urllib.request.urlopen(project_request, timeout=2) as projected:
                    self.assertEqual("ready", json.loads(projected.read())["status"])
                live_refresh_request = urllib.request.Request(
                    f"{base}/api/project?token=viewer-secret&workspace={selected['id']}&refresh=1",
                    method="POST",
                )
                with patch(
                    "scripts.lib.play.journey_view._workspace_catalog",
                    return_value=(
                        [{**selected, "live": False}],
                        {selected["id"]: self.capture["reference"]},
                    ),
                ), patch(
                    "scripts.lib.play.journey_view._catalog_capture",
                    return_value=self.capture,
                ), patch(
                    "scripts.lib.play.journey_view._capture",
                    return_value=self.capture,
                ), patch(
                    "scripts.lib.play.journey_view.schedule_worker",
                    return_value=True,
                ) as schedule:
                    with urllib.request.urlopen(live_refresh_request, timeout=2) as refreshed:
                        refresh_status = json.loads(refreshed.read())
                        self.assertEqual("ready", refresh_status["status"])
                        self.assertEqual("started", refresh_status["projector"])
                    schedule.assert_called_once_with(self.capture)
                with patch(
                    "scripts.lib.play.journey_view._workspace_catalog",
                    return_value=(
                        [{**selected, "live": True}],
                        {selected["id"]: self.capture["reference"]},
                    ),
                ), patch(
                    "scripts.lib.play.journey_view._catalog_capture",
                    return_value=self.capture,
                ), patch(
                    "scripts.lib.play.journey_view._capture",
                    return_value=self.capture,
                ), patch(
                    "scripts.lib.play.journey_view.schedule_worker",
                ) as schedule:
                    with urllib.request.urlopen(live_refresh_request, timeout=2) as refreshed:
                        refresh_status = json.loads(refreshed.read())
                        self.assertEqual("running", refresh_status["projector"])
                    schedule.assert_not_called()
                refresh_request = urllib.request.Request(
                    f"{base}/api/refresh?token=viewer-secret",
                    method="POST",
                )
                with patch(
                    "scripts.lib.play.journey_view_catalog.schedule_worker", return_value=True
                ), patch(
                    "scripts.lib.play.journey_view_catalog._schedule_workspace_projection",
                    return_value=True,
                ):
                    with urllib.request.urlopen(refresh_request, timeout=2) as refreshed:
                        refreshed_index = json.loads(refreshed.read())
                        self.assertEqual(
                            "play.journey-workspace-index/v1",
                            refreshed_index["schema"],
                        )
                        self.assertIn("reconciliation", refreshed_index)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(f"{base}/api/scene", timeout=2)
            self.assertEqual(404, denied.exception.code)
            denied.exception.close()
            cookie_client = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(CookieJar())
            )
            with cookie_client.open(
                f"{base}/?token=viewer-secret", timeout=2
            ) as response:
                self.assertIn("HttpOnly", response.headers["Set-Cookie"])
                self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
            with cookie_client.open(f"{base}/api/workspaces", timeout=2) as response:
                self.assertEqual(
                    "play.journey-workspace-index/v1",
                    json.loads(response.read())["schema"],
                )
            with urllib.request.urlopen(base, timeout=2) as response:
                self.assertIn(b'journey-root', response.read())
            with urllib.request.urlopen(f"{base}/viewer.js", timeout=2) as response:
                viewer = response.read()
                self.assertIn(b'"PLAY"', viewer)
                self.assertIn(b'"FOLLOW"', viewer)
                self.assertIn(b'"ATLAS"', viewer)
                self.assertIn(b"WHY THIS STEP EXISTS", viewer)
                self.assertIn(b"FROZEN VANTAGE", viewer)
                self.assertIn(b"RECORDED EXCHANGES", viewer)
                self.assertIn(b"PLAY RUNTIME", viewer)
                self.assertIn(b"REQUEST", viewer)
                self.assertIn(b"RESPONSE", viewer)
                self.assertIn(b"NEXT SNAPSHOT", viewer)
                self.assertIn(b"ADAPTER", viewer)
                self.assertIn(b"BROWSER", viewer)
                self.assertIn(b"SHELL", viewer)
                self.assertIn(b"Refresh Play projections", viewer)
            with urllib.request.urlopen(
                f"{base}/api/events?token=viewer-secret", timeout=2
            ) as response:
                self.assertEqual("text/event-stream; charset=utf-8", response.headers["Content-Type"])
                self.assertEqual(b"event: journey\n", response.readline())
                event = json.loads(response.readline().removeprefix(b"data: "))
                self.assertEqual(graph["generation"], event["generation"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_selected_tower_exchange_is_lazy_bounded_and_credential_redacted(self) -> None:
        graph = self.graph(self.activities[:1])
        _persist_graph_state(
            self.capture["reference"],
            fingerprint="e" * 64,
            command_count=1,
            activities=self.activities[:1],
            dependencies=[],
            graph=graph,
            root=self.journeys,
        )
        workspace = Path(self.temporary.name) / "workspace"
        response_root = workspace / ".rote" / "responses"
        response_root.mkdir(parents=True)
        database = workspace / ".rote" / "workspace.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "CREATE TABLE command_log (sequence INTEGER PRIMARY KEY, command_type TEXT, "
                "params TEXT, response_ids TEXT, timestamp TEXT, skip_export INTEGER, command_json TEXT)"
            )
            connection.execute(
                "INSERT INTO command_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    1,
                    "Synthetic",
                    json.dumps({"headers": {"Authorization": "Bearer command-secret"}}),
                    "[1]",
                    "2026-08-19T00:00:00Z",
                    0,
                    None,
                ),
            )
            connection.commit()
        (response_root / "@1.json").write_text(
            json.dumps(
                {
                    "request": {
                        "url": "https://example.test/items?access_token=url-secret",
                        "headers": {"Authorization": "Bearer header-secret"},
                    },
                    "response": {"status": 200, "body": {"token": "body-secret", "ok": True}},
                    "tokens": {"total_tokens": 12},
                }
            )
        )
        capture = {**self.capture, "workspace_path": str(workspace)}
        with patch("scripts.lib.play.journey_view_evidence._capture", return_value=capture):
            exchange = _exchange_projection(
                self.capture["reference"], 1, root=self.journeys
            )

        self.assertIsNotNone(exchange)
        assert exchange is not None
        self.assertEqual(EXCHANGE_SCHEMA, exchange["schema"])
        self.assertTrue(exchange["redacted"])
        encoded = json.dumps(exchange)
        self.assertNotIn("url-secret", encoded)
        self.assertNotIn("header-secret", encoded)
        self.assertNotIn("body-secret", encoded)
        self.assertIn("[REDACTED]", encoded)

        interactions = _interaction_projection(
            self.capture["reference"], root=self.journeys
        )
        projected = next(items for items in interactions["sites"].values() if items)[0]
        self.assertEqual(self.activities[0]["kind"], projected["semantic_kind"])

    def test_attached_workspace_reference_resolves_private_exchange(self) -> None:
        graph = self.graph(self.activities[:1])
        _persist_graph_state(
            self.capture["reference"],
            fingerprint="f" * 64,
            command_count=1,
            activities=self.activities[:1],
            dependencies=[],
            graph=graph,
            root=self.journeys,
        )
        workspace = Path(self.temporary.name) / "attached-workspace"
        response_root = workspace / ".rote" / "responses"
        response_root.mkdir(parents=True)
        with closing(sqlite3.connect(workspace / ".rote" / "workspace.db")) as connection:
            connection.execute(
                "CREATE TABLE command_log (sequence INTEGER PRIMARY KEY, command_type TEXT, "
                "params TEXT, response_ids TEXT, timestamp TEXT)"
            )
            connection.execute(
                "INSERT INTO command_log VALUES (?, ?, ?, ?, ?)",
                (1, "HttpRequest", "{}", "[1]", "2026-08-20T00:00:00Z"),
            )
            connection.commit()
        (response_root / "@1.json").write_text(
            json.dumps({"request": {"method": "tools/call"}, "response": {"ok": True}})
        )

        with patch("scripts.lib.play.journey_view_evidence._capture", return_value=None), patch(
            "scripts.lib.play.journey_view_evidence._workspace_capture_for_reference",
            return_value={"workspace_path": str(workspace)},
        ):
            exchange = _exchange_projection(
                self.capture["reference"], 1, root=self.journeys
            )

        self.assertIsNotNone(exchange)
        assert exchange is not None
        self.assertEqual({"ok": True}, exchange["response"])

    def test_view_starts_a_missed_projector_and_waits_for_the_first_graph(self) -> None:
        graph = self.graph(self.activities)
        with patch(
            "scripts.lib.play.journey_view.load_graph",
            side_effect=[None, None, graph],
        ), patch(
            "scripts.lib.play.journey_view._capture", return_value=self.capture
        ), patch(
            "scripts.lib.play.journey_view.schedule_worker", return_value=True
        ) as schedule:
            _ensure_graph_ready(
                self.capture["reference"], root=self.journeys, timeout_seconds=0.5
            )

        schedule.assert_called_once_with(self.capture)


if __name__ == "__main__":
    unittest.main()
