from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.timewindow import CHECKPOINT_SCHEMA, TimeWindowError, next_checkpoint, resolve_window


class TimeWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.end = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)

    def test_checkpoint_supplies_exact_next_window_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            path.write_text(
                json.dumps(
                    {"schema": CHECKPOINT_SCHEMA, "last_seen_at": "2026-08-03T08:30:00Z"}
                )
            )
            start, end = resolve_window(end=self.end, days=1, checkpoint=path)
        self.assertEqual("2026-08-03T08:30:00+00:00", start.isoformat())
        self.assertEqual(self.end, end)

    def test_since_and_checkpoint_cannot_compete(self) -> None:
        with self.assertRaises(TimeWindowError):
            resolve_window(
                end=self.end,
                days=1,
                since="2026-08-03T00:00:00Z",
                checkpoint=Path("unused.json"),
            )

    def test_next_checkpoint_is_host_persistable_data_not_a_write(self) -> None:
        self.assertEqual(
            {"schema": CHECKPOINT_SCHEMA, "last_seen_at": self.end.isoformat()},
            next_checkpoint(self.end),
        )


if __name__ == "__main__":
    unittest.main()
