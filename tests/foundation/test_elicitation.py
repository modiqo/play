from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.elicitation import (
    ElicitationError,
    markdown_fallback,
    native_payload,
    parse_question,
    resolve_question,
)


class ElicitationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.question = parse_question(
            "creator_match",
            {
                "question": "How should I proceed?",
                "selection": "single",
                "choices": [
                    {
                        "id": "use",
                        "label": "Use existing",
                        "description": "Run the matching Play.",
                        "event": "creator_use_selected",
                        "recommended": True,
                    },
                    {
                        "id": "create",
                        "label": "Create distinct",
                        "description": "Explore a separate Play.",
                        "event": "creator_create_selected",
                    },
                ],
            },
        )

    def test_maps_native_surface_without_changing_events(self) -> None:
        for harness, surface in (
            ("codex", "request_user_input"),
            ("claude", "askquestion"),
            ("kimi", "askquestion"),
        ):
            payload = native_payload(self.question, harness)
            self.assertEqual(surface, payload["surface"])
            self.assertEqual(
                ["creator_use_selected", "creator_create_selected"],
                [choice["event"] for choice in payload["choices"]],
            )

    def test_markdown_fallback_is_numbered_and_preserves_recommendation(self) -> None:
        output = markdown_fallback(self.question)
        self.assertIn("1. **Use existing** *(Recommended)*", output)
        self.assertIn("2. **Create distinct**", output)
        self.assertIn("Reply with one number.", output)

    def test_text_prompt_uses_native_input_and_plain_fallback(self) -> None:
        question = parse_question(
            "describe_need",
            {
                "question": "What outcome should the Play accomplish?",
                "selection": "text",
                "input": {"id": "outcome", "label": "Desired outcome", "event": "need_described"},
                "events": {"need_described": ["value"]},
            },
        )
        self.assertEqual("need_described", native_payload(question, "claude")["input"]["event"])
        self.assertIn("Reply with desired outcome.", markdown_fallback(question))

    def test_typed_template_resolves_email_handle_from_context(self) -> None:
        question = parse_question(
            "welcome",
            {
                "question": "How are you, {onboarding.email_handle}? What can I help you with?",
                "template_fields": ["onboarding.email_handle"],
                "selection": "text",
                "input": {"id": "request", "label": "What you need", "event": "described"},
                "events": {"described": ["request.original"]},
            },
        )
        context = {"onboarding": {"email_handle": "chetan"}}
        self.assertEqual(
            "How are you, chetan? What can I help you with?",
            resolve_question(question, context).text,
        )
        self.assertIn("chetan", native_payload(question, "codex", context)["question"])
        self.assertIn("chetan", markdown_fallback(question, context))
        with self.assertRaises(ElicitationError):
            native_payload(question, "codex")

    def test_prompt_placeholders_must_be_declared_exactly(self) -> None:
        with self.assertRaisesRegex(ElicitationError, "match template_fields exactly"):
            parse_question(
                "bad_welcome",
                {
                    "question": "Hello {onboarding.email_handle}?",
                    "selection": "text",
                    "input": {"id": "request", "label": "Request", "event": "described"},
                    "events": {"described": []},
                },
            )

    def test_dynamic_public_owner_choices_bind_typed_payloads(self) -> None:
        question = parse_question(
            "select_public_owner",
            {
                "question": "{publication.owner_summary} Which namespace should own it?",
                "template_fields": ["publication.owner_summary"],
                "selection": "single",
                "choices_from": {
                    "context": "publication.owner_choices",
                    "id_field": "id",
                    "label_field": "display_name",
                    "description_field": "ownership_description",
                    "value_source_field": "owner",
                    "value_field": "publication.owner",
                    "recommended_field": "recommended",
                    "event": "public_owner_selected",
                },
                "choices": [
                    {
                        "id": "cancel",
                        "label": "Cancel",
                        "description": "Stop publication.",
                        "event": "public_owner_declined",
                    }
                ],
            },
        )
        context = {
            "publication": {
                "owner_summary": "Your profile handle `chetan` is already claimed.",
                "owner_choices": [
                    {
                        "id": "profile:chetan",
                        "owner": "chetan",
                        "display_name": "@chetan (profile handle)",
                        "ownership_description": "Use the claimed handle.",
                        "recommended": True,
                    },
                    {
                        "id": "org:chetanconikee",
                        "owner": "chetanconikee",
                        "display_name": "Chetan (chetanconikee)",
                        "ownership_description": "Use the authorized org.",
                        "recommended": False,
                    },
                ],
            }
        }
        payload = native_payload(question, "codex", context)
        self.assertEqual(
            ["profile:chetan", "org:chetanconikee", "cancel"],
            [choice["id"] for choice in payload["choices"]],
        )
        self.assertEqual(
            {"publication.owner": "chetan"}, payload["choices"][0]["payload"]
        )
        self.assertTrue(payload["choices"][0]["recommended"])
        self.assertIn("already claimed", payload["question"])
        self.assertIn("Chetan (chetanconikee)", markdown_fallback(question, context))


if __name__ == "__main__":
    unittest.main()
