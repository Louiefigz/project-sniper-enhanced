"""Regression tests for codec-floor calibration authority."""
from __future__ import annotations

import json
import unittest

from current_render_graph_contract import object_hash
from current_render_oracle_calibrate import _master_policy


class CurrentRenderOracleCalibrationTests(unittest.TestCase):
    """The retained policy must be the same JSON value that is hashed."""

    def test_master_policy_is_projected_to_the_json_domain(self) -> None:
        policy = _master_policy()
        self.assertIsInstance(policy["audio"]["music_duck_db"], list)
        self.assertIn("30", policy["encode"]["bitrate_by_fps"])
        self.assertEqual(policy, json.loads(json.dumps(policy, allow_nan=False)))
        self.assertEqual(len(object_hash(policy)), 64)


if __name__ == "__main__":
    unittest.main()
