"""Release gates: no uploads, signing, or Apple requests during tests."""
import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build
import release


class DistributionTests(unittest.TestCase):
    def test_partial_signing_configuration_is_rejected(self):
        parser = argparse.ArgumentParser()
        for identity, profile, dmg in [("Developer ID Application: Test", None, True),
                                       (None, "profile", True), ("-", "profile", True),
                                       ("Developer ID Application: Test", "profile", False)]:
            with self.subTest(identity=identity, profile=profile, dmg=dmg), self.assertRaises(SystemExit):
                build.validate_distribution_args(parser, SimpleNamespace(identity=identity, notary_profile=profile, dmg=dmg))

    def test_apple_rejection_stops_distribution_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "notary.json"
            with patch.object(build, "run", return_value=SimpleNamespace(returncode=65, stdout=json.dumps({"status": "Invalid", "id": "submission"}))):
                with self.assertRaisesRegex(SystemExit, "not accepted"):
                    build.notarize(Path("app.zip"), "profile", receipt)
            self.assertEqual(json.loads(receipt.read_text())["status"], "Invalid")

    def test_review_dirty_stale_and_modified_builds_cannot_enter_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "Play.dmg"
            artifact.write_bytes(b"test artifact")
            valid = {"schema_version": 1, "app_version": build.APP_VERSION, "source_dirty": False,
                     "distribution": "notarized", "source_commit": "commit", "architectures": ["arm64", "x86_64"],
                     "minimum_macos": "13.0", "notarization": {"app": "app-id", "dmg": "dmg-id"},
                     "artifact": artifact.name, "size": artifact.stat().st_size,
                     "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
            self.assertEqual(release.validate_manifest(valid, artifact, "commit"), valid["sha256"])
            for key, value in [("distribution", "local-review"), ("source_dirty", True),
                               ("source_commit", "old-commit"), ("architectures", ["arm64"]),
                               ("notarization", {"app": "app-id"}), ("sha256", "0" * 64), ("artifact", "other.dmg")]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    release.validate_manifest({**valid, key: value}, artifact, "commit")
            artifact.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                release.validate_manifest(valid, artifact, "commit")


if __name__ == "__main__":
    unittest.main()
