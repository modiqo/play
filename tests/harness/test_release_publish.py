from __future__ import annotations

import unittest

from scripts.release.publish_play import (
    ReleaseError,
    release_tag,
    replace_selector,
    selector_release,
)


SELECTOR = """#!/bin/sh
set -eu
release=v0.4.56
"""


class ReleasePublishTest(unittest.TestCase):
    def test_release_tag_requires_semantic_version(self) -> None:
        self.assertEqual("v0.4.58", release_tag("0.4.58\n"))
        with self.assertRaises(ReleaseError):
            release_tag("0.4")

    def test_selector_release_requires_one_assignment(self) -> None:
        self.assertEqual("v0.4.56", selector_release(SELECTOR))
        with self.assertRaises(ReleaseError):
            selector_release("#!/bin/sh\n")
        with self.assertRaises(ReleaseError):
            selector_release(SELECTOR + "release=v0.4.57\n")

    def test_replace_selector_changes_only_the_release(self) -> None:
        updated = replace_selector(SELECTOR, "v0.4.58")
        self.assertEqual("v0.4.58", selector_release(updated))
        self.assertEqual(SELECTOR, replace_selector(SELECTOR, "v0.4.56"))


if __name__ == "__main__":
    unittest.main()
