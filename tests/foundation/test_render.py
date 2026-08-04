from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.render import compact_json, join_sections, json_text


class RenderTest(unittest.TestCase):
    def test_json_renderers_are_deterministic_and_preserve_unicode(self) -> None:
        self.assertEqual('{"a": 1, "é": 2}', compact_json({"é": 2, "a": 1}))
        self.assertIn('"é": 2', json_text({"é": 2}))

    def test_join_sections_omits_empty_sections(self) -> None:
        self.assertEqual("one\n\ntwo", join_sections(["one", "", "two"]))


if __name__ == "__main__":
    unittest.main()
