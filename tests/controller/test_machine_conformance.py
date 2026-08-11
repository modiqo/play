from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.machine import validate_bundle
from play.handoff import capability_policy
from play.executors import action_executor


CONTROLLER = ROOT / "references" / "controller"
MACHINE = yaml.safe_load((CONTROLLER / "machine.yaml").read_text())
ACTIONS_DOC = yaml.safe_load((CONTROLLER / "actions.yaml").read_text())
ACTIONS = ACTIONS_DOC["actions"]
PROMPTS = yaml.safe_load((CONTROLLER / "prompts.yaml").read_text())["prompts"]
FIXTURES = yaml.safe_load((Path(__file__).parent / "fixtures" / "paths.yaml").read_text())
CONTEXT = json.loads((CONTROLLER / "context.schema.json").read_text())
SKILL_TEXT = (ROOT / "SKILL.md").read_text()


def transition(state: str, event: str, guards: dict[str, bool] | None = None) -> str:
    branches = MACHINE["states"][state].get("on", {}).get(event)
    if branches is None:
        raise KeyError(f"{state} does not accept {event}")
    active = guards or {}
    for branch in branches:
        guard = branch.get("guard")
        if guard is None or active.get(guard, False):
            return branch["target"]
    raise KeyError(f"{state}.{event} has no satisfied branch")


class MachineConformanceTest(unittest.TestCase):
    def test_every_action_has_one_closed_executor(self) -> None:
        executors = {
            name: action_executor(name, action) for name, action in ACTIONS.items()
        }
        self.assertNotIn(None, executors.values())
        self.assertEqual("runtime", executors["run_registry_play"])
        self.assertEqual("runtime", executors["inspect_saved_play"])
        for action in ACTIONS.values():
            command = action.get("command")
            if command is not None:
                self.assertTrue(command.startswith("scripts/bin/"), command)

    def test_declared_path_fixtures(self) -> None:
        for fixture in FIXTURES["cases"]:
            with self.subTest(fixture=fixture["name"]):
                current = fixture["steps"][0]["state"]
                visited: list[str] = []
                for step in fixture["steps"]:
                    self.assertEqual(step["state"], current)
                    visited.append(current)
                    current = transition(current, step["event"], step.get("guards"))
                    self.assertEqual(step["target"], current)
                visited.append(current)
                self.assertEqual(fixture["terminal"], current)
                for excluded in fixture.get("excludes", []):
                    self.assertNotIn(excluded, visited)
                for included in fixture.get("includes_once", []):
                    self.assertEqual(1, visited.count(included))

    def test_python_validator_accepts_bundle(self) -> None:
        summary = validate_bundle(ROOT)
        self.assertGreaterEqual(summary.states, 34)
        self.assertGreater(summary.transitions, summary.states)

    def test_unknown_event_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            transition("use_run", "invented_event")

    def test_incomplete_search_is_blocked(self) -> None:
        self.assertEqual(
            "blocked", transition("search", "search_ready", {"search_is_complete": False})
        )

    def test_terminal_states_accept_no_events(self) -> None:
        for state in MACHINE["terminal"]:
            self.assertFalse(MACHINE["states"][state].get("on", {}))

    def test_context_allows_only_the_private_runtime_continuation_store(self) -> None:
        self.assertIn("~/.rote-play/continuations", SKILL_TEXT)
        self.assertEqual("Play logical controller context", CONTEXT["title"])
        self.assertIn("Only the Play runtime continuation backend", CONTEXT["$comment"])
        self.assertIn("24-hour expiry", CONTEXT["$comment"])

    def test_empty_invocation_uses_typed_live_identity_or_setup(self) -> None:
        self.assertEqual("invoke", MACHINE["initial"])
        self.assertEqual(
            "scripts/bin/play-onboarding classify --stdin --json",
            ACTIONS["classify_play_invocation"]["command"],
        )
        self.assertEqual(
            "onboarding_probe",
            MACHINE["states"]["invoke"]["on"]["empty_play_invocation"][0]["target"],
        )
        self.assertEqual(
            "search",
            MACHINE["states"]["invoke"]["on"]["outcome_play_invocation"][0][
                "target"
            ],
        )
        available = MACHINE["states"]["onboarding_probe"]["on"]["rote_available"]
        missing = MACHINE["states"]["onboarding_probe"]["on"]["rote_missing"]
        self.assertEqual("onboarding_identity", available[0]["target"])
        self.assertEqual("onboarding_setup", missing[0]["target"])
        self.assertEqual(
            "scripts/bin/play-onboarding identity --stdin --json",
            ACTIONS["inspect_onboarding_identity"]["command"],
        )
        self.assertEqual(
            "onboarding_setup",
            MACHINE["states"]["onboarding_identity"]["on"][
                "onboarding_identity_setup_required"
            ][0]["target"],
        )
        self.assertEqual(
            "onboarding_probe",
            MACHINE["states"]["onboarding_setup"]["on"]["rote_setup_completed"][0][
                "target"
            ],
        )
        self.assertEqual(
            "onboarding_experience",
            MACHINE["states"]["onboarding_identity"]["on"][
                "onboarding_identity_ready"
            ][0]["target"],
        )
        self.assertEqual(
            "onboarding_first_present",
            MACHINE["states"]["onboarding_experience"]["on"][
                "onboarding_first_use"
            ][0]["target"],
        )
        self.assertEqual(
            "onboarding_welcome",
            MACHINE["states"]["onboarding_experience"]["on"][
                "onboarding_returning"
            ][0]["target"],
        )
        setup_policy = " ".join(ACTIONS["handoff_rote_setup"]["command_policy"])
        self.assertIn("Invoke the rote-setup skill", setup_policy)
        self.assertIn("Do not run an installer", setup_policy)
        prompt = PROMPTS["welcome_play_request"]
        self.assertEqual(["onboarding.email_handle"], prompt["template_fields"])
        self.assertIn("{onboarding.email_handle}", prompt["question"])
        first_prompt = PROMPTS["choose_first_use_path"]
        self.assertEqual("Run Hello", first_prompt["choices"][0]["label"])
        self.assertTrue(first_prompt["choices"][0]["recommended"])
        self.assertEqual("Create team space", first_prompt["choices"][1]["label"])
        self.assertEqual(
            "use_inspect",
            MACHINE["states"]["onboarding_first_offer"]["on"][
                "onboarding_starter_selected"
            ][0]["target"],
        )
        self.assertEqual(
            "local-write", ACTIONS["remember_first_use_orientation"]["effect"]
        )

    def test_play_uri_uses_inspect_or_bounded_public_card(self) -> None:
        available = MACHINE["states"]["onboarding_probe"]["on"]["rote_available"]
        missing = MACHINE["states"]["onboarding_probe"]["on"]["rote_missing"]
        self.assertEqual("use_inspect", available[1]["target"])
        self.assertEqual("onboarding_card_fetch", missing[1]["target"])
        card_action = ACTIONS["fetch_onboarding_play_card"]
        self.assertEqual("read", card_action["effect"])
        self.assertEqual(
            "scripts/bin/play-onboarding card --stdin --json", card_action["command"]
        )
        policy = " ".join(card_action["command_policy"])
        self.assertIn("canonical HTTPS play.modiqo.ai", policy)
        self.assertIn("never execute an install or run action", policy)
        onboarding = CONTEXT["$defs"]["onboarding"]
        for field in (
            "intent",
            "rote_status",
            "rote_command",
            "identity_status",
            "email",
            "email_handle",
            "play_uri",
            "setup_status",
            "card",
            "experience_status",
            "orientation_status",
            "starter_reference",
            "starter_status",
            "activation_status",
        ):
            self.assertIn(field, onboarding["required"])

    def test_every_prompt_has_structured_choices(self) -> None:
        for name, prompt in PROMPTS.items():
            with self.subTest(prompt=name):
                self.assertIn(prompt["selection"], {"single", "multiple", "text"})
                self.assertTrue(prompt["question"].strip().endswith("?"))
                for choice in prompt.get("choices", []):
                    self.assertTrue(choice["label"])
                    self.assertTrue(choice["description"])

    def test_saved_play_is_inspected_before_completed(self) -> None:
        indexed = MACHINE["states"]["index"]["on"]["play_indexed"][0]
        self.assertEqual("saved_inspect", indexed["target"])
        self.assertEqual(
            "inspect_saved_play", MACHINE["states"]["saved_inspect"]["entry"]["action"]
        )
        inspected = MACHINE["states"]["saved_inspect"]["on"]["saved_play_inspected"][0]
        self.assertEqual("publication_credentials", inspected["target"])
        self.assertEqual("birth_present", MACHINE["states"]["saved_inspect"]["on"]["saved_play_inspected"][1]["target"])
        self.assertEqual(
            "inspect_publication_credentials",
            MACHINE["states"]["publication_credentials"]["entry"]["action"],
        )
        self.assertEqual(
            "publication_smoke",
            MACHINE["states"]["publication_credentials"]["on"]["associated_credentials_verified"][0]["target"],
        )
        self.assertEqual(
            "smoke_publication", MACHINE["states"]["publication_smoke"]["entry"]["action"]
        )
        self.assertEqual(
            "birth_present",
            MACHINE["states"]["publication_smoke"]["on"]["public_smoke_verified"][0]["target"],
        )
        self.assertEqual(
            "present_birth_certificate", MACHINE["states"]["birth_present"]["entry"]["action"]
        )
        birth_presented = MACHINE["states"]["birth_present"]["on"][
            "birth_certificate_presented"
        ]
        self.assertEqual("save_choice_private", birth_presented[0]["guard"])
        self.assertEqual("team_invite_offer", birth_presented[0]["target"])
        self.assertEqual("completed", birth_presented[1]["target"])

    def test_team_invite_flow_is_shared_by_onboarding_and_private_creation(self) -> None:
        self.assertEqual(
            "onboarding_team_handle",
            MACHINE["states"]["onboarding_first_offer"]["on"][
                "onboarding_team_selected"
            ][0]["target"],
        )
        self.assertEqual(
            "onboarding_team_handle",
            MACHINE["states"]["onboarding_activation_offer"]["on"][
                "onboarding_team_selected"
            ][0]["target"],
        )
        self.assertEqual("rote-org", ACTIONS["create_team_space"]["specialist"])
        self.assertEqual("rote-org", ACTIONS["invite_team_member"]["specialist"])
        self.assertEqual("external-write", ACTIONS["create_team_space"]["effect"])
        self.assertEqual("external-write", ACTIONS["invite_team_member"]["effect"])
        self.assertEqual(
            "team_invite_offer",
            MACHINE["states"]["onboarding_team_present"]["on"][
                "team_loop_presented"
            ][0]["target"],
        )
        self.assertEqual(
            "team_invite_offer",
            MACHINE["states"]["team_invite_execute"]["on"][
                "team_invite_ready"
            ][0]["target"],
        )
        save_choices = PROMPTS["private_public_or_skip"]["choices"]
        self.assertEqual("Team", save_choices[0]["label"])
        self.assertEqual("Community", save_choices[1]["label"])
        self.assertIn("X and LinkedIn", save_choices[1]["description"])

    def test_birth_certificate_preserves_uris_social_copy_and_trace_learning(self) -> None:
        published = ACTIONS["publish_public"]["events"]["play_published"]
        self.assertIn("publication.uri", published)
        self.assertIn("publication.install_uri", published)
        self.assertEqual(
            "scripts/bin/play-certificate --stdin --json",
            ACTIONS["present_birth_certificate"]["command"],
        )
        policy = " ".join(ACTIONS["present_birth_certificate"]["command_policy"])
        self.assertIn("ready to paste into X and LinkedIn", policy)
        self.assertIn("Never invent, reconstruct, shorten, or silently omit", policy)
        self.assertIn("public URLs or social copy", policy)
        self.assertIn("same redacted trace", policy)
        self.assertIn("we did an excellent job", policy)
        publication = CONTEXT["$defs"]["publication"]
        for field in (
            "title",
            "description",
            "uri",
            "install_uri",
            "content_hash",
            "share_copy",
            "presentation_ref",
            "presented",
        ):
            self.assertIn(field, publication["required"])
        birth = CONTEXT["$defs"]["birth"]
        for field in (
            "certificate_presented",
            "certificate_ref",
            "certificate_ns",
            "trace_learning",
        ):
            self.assertIn(field, birth["required"])

    def test_publication_gate_compares_credential_contract_then_smokes_exact_uri(self) -> None:
        credential_action = ACTIONS["inspect_publication_credentials"]
        self.assertEqual("read", credential_action["effect"])
        self.assertEqual(
            "scripts/bin/play-publication-gate credentials --stdin --json",
            credential_action["command"],
        )
        credential_policy = " ".join(credential_action["command_policy"])
        self.assertIn("source, version, fingerprint, auth family", credential_policy)
        self.assertIn("Never inspect, print, hash, copy, or persist a credential value", credential_policy)
        self.assertIn("equal fingerprints as insufficient", credential_policy)

        smoke_action = ACTIONS["smoke_publication"]
        self.assertEqual("mixed", smoke_action["effect"])
        self.assertEqual(
            "scripts/bin/play-publication-gate smoke --stdin --json", smoke_action["command"]
        )
        smoke_policy = " ".join(smoke_action["command_policy"])
        self.assertIn("exactly one rote play run", smoke_policy)
        self.assertIn("fresh temporary working directory under /tmp", smoke_policy)

        validation = CONTEXT["$defs"]["publicationValidation"]
        for field in (
            "credential_status",
            "adapter_contracts",
            "credential_contract_sha256",
            "credential_check_ns",
            "smoke_status",
            "smoke_exact_reference",
            "smoke_output_sha256",
            "smoke_ns",
            "isolated_workdir",
        ):
            self.assertIn(field, validation["required"])

    def test_publication_mismatch_or_smoke_failure_blocks_presentation(self) -> None:
        self.assertEqual(
            "blocked",
            MACHINE["states"]["publication_credentials"]["on"][
                "associated_credentials_invalid"
            ][0]["target"],
        )
        self.assertEqual(
            "blocked",
            MACHINE["states"]["publication_smoke"]["on"]["public_smoke_failed"][0][
                "target"
            ],
        )

    def test_birth_is_captured_before_publish_and_bound_before_index(self) -> None:
        released = MACHINE["states"]["author_release"]["on"]["flow_released"][0]
        self.assertEqual("birth_capture", released["target"])
        self.assertEqual("released_candidate_is_unpublished", released["guard"])
        self.assertEqual(
            "blocked",
            MACHINE["states"]["author_release"]["on"]["flow_released"][1]["target"],
        )
        self.assertEqual(
            "blocked",
            MACHINE["states"]["author_release"]["on"][
                "publication_boundary_violated"
            ][0]["target"],
        )
        self.assertEqual(
            "capture_play_birth", MACHINE["states"]["birth_capture"]["entry"]["action"]
        )
        expected_guards = {
            "private_publish": "private_publication_matches_captured_birth",
            "public_publish": "public_publication_matches_captured_birth",
        }
        for state, expected_guard in expected_guards.items():
            self.assertEqual(
                "birth_bind", MACHINE["states"][state]["on"]["play_published"][0]["target"]
            )
            self.assertEqual(
                expected_guard,
                MACHINE["states"][state]["on"]["play_published"][0]["guard"],
            )
            self.assertEqual(
                "blocked", MACHINE["states"][state]["on"]["play_published"][1]["target"]
            )
        self.assertEqual("index", MACHINE["states"]["birth_bind"]["on"]["birth_bound"][0]["target"])
        self.assertEqual("local-write", ACTIONS["capture_play_birth"]["effect"])
        self.assertEqual("local-write", ACTIONS["bind_play_birth"]["effect"])

    def test_release_and_publication_are_distinct_closed_handoffs(self) -> None:
        release = ACTIONS["author_release"]
        self.assertEqual("rote-flow-authoring", release["specialist"])
        self.assertIn("candidate.publication_status", release["events"]["flow_released"])
        self.assertIn("publication_boundary_violated", release["events"])
        release_policy = " ".join(release["command_policy"])
        self.assertIn("stop before every registry push", release_policy)
        self.assertIn("Never delegate an end-to-end release-and-publish request", release_policy)

        for name in ("publish_private", "publish_public"):
            publication = ACTIONS[name]
            self.assertEqual("rote-registry", publication["specialist"])
            self.assertIn("birth.sha256", publication["input_required"])
            self.assertIn("birth.capture_ref", publication["input_required"])
            self.assertIn("birth.sha256", publication["events"]["play_published"])
            self.assertIn(
                "publication.birth_sha256", publication["events"]["play_published"]
            )
            policy = " ".join(publication["command_policy"])
            self.assertIn("publication-only handoff", policy)
            self.assertIn("Return the captured birth SHA unchanged", policy)

        candidate = CONTEXT["$defs"]["candidate"]
        self.assertIn("publication_status", candidate["required"])
        self.assertEqual(
            ["unknown", "unpublished", "published"],
            candidate["properties"]["publication_status"]["enum"],
        )
        self.assertIn(
            "a saved Play is complete only when its birth certificate has been presented",
            SKILL_TEXT.replace("\n", " "),
        )

    def test_public_namespace_is_resolved_before_save_and_release(self) -> None:
        self.assertEqual(
            "save_prepare",
            MACHINE["states"]["crystallize"]["on"]["candidate_ready"][0]["target"],
        )
        self.assertEqual(
            "resolve_public_owner",
            MACHINE["states"]["save_prepare"]["entry"]["action"],
        )
        action = ACTIONS["resolve_public_owner"]
        self.assertEqual("play", action["owner"])
        self.assertEqual("read", action["effect"])
        self.assertEqual("scripts/bin/play-public-owner --json", action["command"])
        policy = " ".join(action["command_policy"])
        self.assertIn("rote registry whoami --verbose", policy)
        self.assertIn("rote registry org list --json", policy)
        self.assertIn("never run or recommend rote profile set-handle", policy)

        public = MACHINE["states"]["save_offer"]["on"]["save_public"]
        self.assertEqual("public_owner_is_resolved", public[0]["guard"])
        self.assertEqual("author_release", public[0]["target"])
        self.assertEqual("public_owner_choice_is_required", public[1]["guard"])
        self.assertEqual("public_owner_offer", public[1]["target"])
        self.assertEqual("blocked", public[2]["target"])
        self.assertEqual(
            "author_release",
            MACHINE["states"]["public_owner_offer"]["on"][
                "public_owner_selected"
            ][0]["target"],
        )
        self.assertNotIn("public_owner", MACHINE["states"])
        self.assertEqual(
            "public_publish",
            MACHINE["states"]["birth_capture"]["on"]["birth_captured"][1]["target"],
        )

        save_prompt = PROMPTS["private_public_or_skip"]
        self.assertEqual(["publication.owner_summary"], save_prompt["template_fields"])
        owner_prompt = PROMPTS["select_public_owner"]
        self.assertEqual(
            "publication.owner_choices", owner_prompt["choices_from"]["context"]
        )
        self.assertEqual("owner", owner_prompt["choices_from"]["value_source_field"])
        publication = CONTEXT["$defs"]["publication"]
        for field in (
            "owner_resolution",
            "profile_handle",
            "owner_choices",
            "owner_summary",
            "owner_probe_ref",
            "owner_probe_ns",
        ):
            self.assertIn(field, publication["required"])

    def test_birth_lookup_is_an_owner_local_read(self) -> None:
        self.assertEqual(
            "birth_show", MACHINE["states"]["qualify"]["on"]["play_birth_request"][0]["target"]
        )
        self.assertEqual("read", ACTIONS["show_play_birth"]["effect"])
        self.assertEqual(
            "scripts/bin/play-birth show <birth.selector> --json",
            ACTIONS["show_play_birth"]["command"],
        )

    def test_first_class_play_commands_cannot_be_decomposed(self) -> None:
        self.assertEqual(
            "use_inspect", MACHINE["states"]["qualify"]["on"]["exact_play_request"][0]["target"]
        )
        self.assertEqual(
            "scripts/bin/play-inspect <match.reference> --json",
            ACTIONS["inspect_registry_play"]["command"],
        )
        self.assertEqual("deterministic", ACTIONS["run_registry_play"]["kind"])
        self.assertEqual(
            "scripts/bin/play-run --stdin --json",
            ACTIONS["run_registry_play"]["command"],
        )
        self.assertIn(
            "never treat its failure as authorization for a manual fallback",
            SKILL_TEXT.replace("\n", " "),
        )
        self.assertIn(
            "Never decompose `rote play run`",
            SKILL_TEXT.replace("\n", " "),
        )

    def test_unified_search_is_actionable(self) -> None:
        self.assertEqual(
            "scripts/bin/play-search <request.intent> --limit 5 --json",
            ACTIONS["search_authorized_plays"]["command"],
        )
        self.assertEqual("deterministic", ACTIONS["classify_adequacy"]["kind"])

    def test_awareness_writes_only_local_memory_until_inspected_approval(self) -> None:
        self.assertEqual(
            "awareness_collect",
            MACHINE["states"]["qualify"]["on"]["play_awareness_request"][0]["target"],
        )
        self.assertEqual("local-write", ACTIONS["collect_awareness_digest"]["effect"])
        self.assertEqual(
            "scripts/bin/play-digest --remember --days <awareness.window_days> --json",
            ACTIONS["collect_awareness_digest"]["command"],
        )
        self.assertEqual(
            "use_inspect",
            MACHINE["states"]["awareness_offer"]["on"]["awareness_play_selected"][0]["target"],
        )
        self.assertEqual(
            "completed",
            MACHINE["states"]["awareness_collect"]["on"]["awareness_unchanged"][0]["target"],
        )

    def test_creator_intent_searches_before_standby_and_skips_generic_offer(self) -> None:
        self.assertEqual(
            "creator_search",
            MACHINE["states"]["qualify"]["on"]["play_creation_request"][0]["target"],
        )
        self.assertEqual(
            "creator_classify",
            MACHINE["states"]["creator_search"]["on"]["creator_search_ready"][0]["target"],
        )
        self.assertEqual(
            "standby_exit",
            MACHINE["states"]["creator_classify"]["on"]["creator_no_match"][0]["target"],
        )

    def test_every_unserved_outcome_arms_the_save_hook_and_steps_aside(self) -> None:
        for state, event, branch in (
            ("classify", "no_match", 0),
            ("classify", "partial_match", 0),
            ("classify", "uncertain_match", 0),
            ("classify", "full_match", 1),
            ("creator_classify", "creator_no_match", 0),
            ("creator_offer", "creator_adapt_selected", 0),
            ("creator_offer", "creator_create_selected", 0),
            ("use_run", "play_drifted", 0),
            ("use_verify", "outcome_not_verified", 0),
            ("qualify", "play_excluded", 0),
        ):
            with self.subTest(state=state, event=event):
                self.assertEqual(
                    "standby_exit",
                    MACHINE["states"][state]["on"][event][branch]["target"],
                )
        self.assertEqual(
            "record_standby", MACHINE["states"]["standby_exit"]["entry"]["action"]
        )
        self.assertEqual(
            "scripts/bin/play-standby record --stdin --json",
            ACTIONS["record_standby"]["command"],
        )
        self.assertEqual(
            "exited",
            MACHINE["states"]["standby_exit"]["on"]["standby_recorded"][0]["target"],
        )

    def test_settled_reentry_judges_the_trace_before_any_save_offer(self) -> None:
        self.assertEqual(
            "save_judge",
            MACHINE["states"]["invoke"]["on"]["settled_task_invocation"][0]["target"],
        )
        judge = ACTIONS["judge_save_worthiness"]
        self.assertEqual("evaluator", judge["kind"])
        policy = " ".join(judge["command_policy"])
        self.assertIn("trace evidence, not conversation prose", policy)
        self.assertIn("recurrence prior", policy)
        self.assertIn("failed or abandoned task", policy)
        self.assertEqual(
            "crystallize",
            MACHINE["states"]["save_judge"]["on"]["worth_saving"][0]["target"],
        )
        self.assertEqual(
            "exited",
            MACHINE["states"]["save_judge"]["on"]["not_worth_saving"][0]["target"],
        )
        incoming = {
            state_name
            for state_name, state in MACHINE["states"].items()
            for branches in state.get("on", {}).values()
            for branch in branches
            if branch["target"] == "crystallize"
        }
        self.assertEqual({"save_judge"}, incoming)

    def test_open_text_prompts_have_stable_input_events(self) -> None:
        for name in ("describe_awareness_need", "describe_creator_need"):
            prompt = PROMPTS[name]
            self.assertEqual("text", prompt["selection"])
            self.assertIn(prompt["input"]["event"], prompt["events"])

    def test_every_run_path_is_inspected_and_remote_pulls_are_approved(self) -> None:
        self.assertEqual(
            "use_decide", MACHINE["states"]["use_inspect"]["on"]["play_inspected"][0]["target"]
        )
        self.assertEqual(
            "use_prepare", MACHINE["states"]["use_decide"]["on"]["local_play_ready"][0]["target"]
        )
        self.assertEqual(
            "use_offer",
            MACHINE["states"]["use_decide"]["on"]["remote_pull_required"][0]["target"],
        )
        self.assertEqual(
            "use_prepare", MACHINE["states"]["use_offer"]["on"]["play_run_approved"][0]["target"]
        )
        incoming = {
            state_name
            for state_name, state in MACHINE["states"].items()
            for branches in state.get("on", {}).values()
            for branch in branches
            if branch["target"] == "use_prepare"
        }
        self.assertEqual({"use_decide", "use_offer"}, incoming)
        self.assertEqual(
            "use_run",
            MACHINE["states"]["use_prepare"]["on"]["play_run_handoff_ready"][0]["target"],
        )

    def test_successful_output_passes_directly_to_verification(self) -> None:
        self.assertEqual(
            "use_verify",
            MACHINE["states"]["use_run"]["on"]["play_run_ready"][0]["target"],
        )
        incoming = {
            state_name
            for state_name, state in MACHINE["states"].items()
            for branches in state.get("on", {}).values()
            for branch in branches
            if branch["target"] == "use_verify"
        }
        self.assertEqual({"use_run"}, incoming)
        self.assertNotIn("format_run_output", ACTIONS)
        self.assertNotIn("use_output", MACHINE["states"])
        receipt_policy = " ".join(ACTIONS["build_receipt"]["command_policy"])
        self.assertIn("Preserve output.primary exactly as received", receipt_policy)
        self.assertIn("never wrap, summarize, convert, or decorate it", receipt_policy)

    def test_run_output_policy_forbids_summary_results(self) -> None:
        policy = " ".join(ACTIONS["run_registry_play"]["command_policy"])
        self.assertIn("Never request summary output", policy)
        self.assertIn("compact Play summary cannot prove full detail", policy)
        self.assertIn("exactly one rote play run", policy)
        self.assertEqual(
            "verify_play_output", MACHINE["states"]["use_verify"]["entry"]["action"]
        )
        self.assertEqual("detailed", CONTEXT["$defs"]["outputPolicy"]["properties"]["mode"]["const"])

    def test_specialist_registries_stay_closed(self) -> None:
        specialists = [
            "rote-using-adapters",
            "rote-shell",
            "rote-browse",
            "rote-workspace",
        ]
        self.assertEqual(specialists, ACTIONS_DOC["specialist_owners"])
        self.assertEqual(
            ["rote-adapter-create", "rote-adapter-config"],
            ACTIONS_DOC["adapter_specialist_owners"],
        )
        self.assertEqual(
            [*specialists, None],
            CONTEXT["$defs"]["execution"]["properties"]["owner"]["enum"],
        )
        self.assertEqual(
            ["installed", "catalog", "provided_spec", "provider_docs"],
            capability_policy("rote-using-adapters", ["call"])["discovery_order"],
        )
        handoff = json.loads((CONTROLLER / "handoff.schema.json").read_text())
        self.assertEqual(
            CONTEXT["$defs"]["adapterChoice"]["required"],
            handoff["$defs"]["adapterChoice"]["required"],
        )

    def test_recoverable_auth_uses_separate_approved_repair_loop(self) -> None:
        self.assertEqual(
            "use_auth_repair_offer",
            MACHINE["states"]["use_run"]["on"]["play_auth_repair_required"][0][
                "target"
            ],
        )
        self.assertEqual(
            "approve_auth_repair", MACHINE["states"]["use_auth_repair_offer"]["prompt"]
        )
        self.assertEqual(
            "use_auth_repair_handoff",
            MACHINE["states"]["use_auth_repair_offer"]["on"]["auth_repair_approved"][0][
                "target"
            ],
        )
        self.assertEqual(
            "blocked",
            MACHINE["states"]["use_auth_repair_offer"]["on"]["auth_repair_declined"][0][
                "target"
            ],
        )
        self.assertEqual(
            "rote-adapter-config",
            CONTEXT["$defs"]["authRepair"]["properties"]["owner"]["enum"][0],
        )
        self.assertNotIn("rote-adapter-config", ACTIONS_DOC["specialist_owners"])
        self.assertEqual(
            "scripts/bin/play-handoff prepare-auth-repair --stdin --json",
            ACTIONS["prepare_auth_repair_handoff"]["command"],
        )
        self.assertEqual(
            "scripts/bin/play-handoff verify-auth-repair --stdin --json",
            ACTIONS["validate_auth_repair_receipt"]["command"],
        )
        self.assertEqual(
            "use_inspect",
            MACHINE["states"]["use_auth_repair_receipt"]["on"][
                "specialist_auth_repair_ready"
            ][0]["target"],
        )
        self.assertEqual(
            "blocked",
            MACHINE["states"]["use_auth_repair_receipt"]["on"][
                "auth_repair_receipt_invalid"
            ][0]["target"],
        )
        self.assertIn("Never place raw credentials", SKILL_TEXT)

    def test_search_selection_is_inspection_only(self) -> None:
        self.assertEqual(
            "search_offer",
            MACHINE["states"]["search_present"]["on"]["search_presented"][0]["target"],
        )
        self.assertEqual(
            "use_inspect",
            MACHINE["states"]["search_offer"]["on"]["search_play_selected"][0]["target"],
        )


if __name__ == "__main__":
    unittest.main()
