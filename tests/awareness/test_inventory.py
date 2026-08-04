import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play import inventory as PLAY_INVENTORY


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.organizations = [
            PLAY_INVENTORY.Organization("alpha", "Alpha"),
            PLAY_INVENTORY.Organization("beta", "Beta Team"),
        ]
        self.flows = {
            "alpha": [
                {"name": "private-one", "visibility": "private"},
                {"name": "public-one", "visibility": "public"},
            ],
            "beta": [],
        }

    def test_organization_table_has_member_and_visibility_counts(self):
        output = PLAY_INVENTORY.render_organizations(
            self.organizations, self.flows, {"alpha": 3, "beta": 1}
        )
        self.assertIn("| Alpha (`alpha`) | 3 | 1 | 1 | 2 |", output)
        self.assertIn("| Beta Team (`beta`) | 1 | 0 | 0 | 0 |", output)

    def test_play_view_groups_private_and_public_and_shows_empty_groups(self):
        output = PLAY_INVENTORY.render_plays(self.organizations, self.flows)
        self.assertIn("### Private (1)\n\n- `private-one`", output)
        self.assertIn("### Public (1)\n\n- `public-one`", output)
        self.assertIn("## Beta Team (`beta`) — 0", output)
        self.assertIn("### Private (0)\n\n— None", output)


if __name__ == "__main__":
    unittest.main()
