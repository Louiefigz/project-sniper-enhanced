"""Private continuation binding and non-interfering timer fault checks."""
from __future__ import annotations

import copy
import sys
import unittest
from unittest.mock import patch

from graphics import comp_capability_resume as resume
from graphics.comp_capability_timing import phase_timings
from graphics.comp_capability_budget import projection


def states() -> tuple:
    """Deliberate runner-only version delta, no renderer/measurement waiver."""
    old = {"renderBuild": {"same": "build"}, "motionSourceDigest": "same-motion",
        "measurementSources": {"graphics/comp_capability_refresh.py": resume.RUNNER_SHA256,
            "graphics/comp_catalog_probe.py": "probe", "color/deadline.py": "deadline",
            "planner/graphics_anchors.py": "anchors"}}
    current = copy.deepcopy(old)
    current["measurementSources"]["graphics/comp_capability_refresh.py"] = "new-reviewed-runner"
    current["measurementSources"]["graphics/comp_capability_resume.py"] = "new-reader"
    current["measurementSources"]["graphics/comp_capability_timing.py"] = "new-timer"
    return old, current


class CapabilityResumeBindingTests(unittest.TestCase):
    def test_renderer_measurement_and_motion_cannot_be_changed_as_runner_delta(self) -> None:
        for field in ("renderBuild", "motionSourceDigest", "measurementSources"):
            old, current = states()
            resume._source_binding(old, current)
            if field == "measurementSources":
                current[field]["graphics/comp_catalog_probe.py"] = "changed"
            else:
                current[field] = "changed"
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                resume._source_binding(old, current)

    def test_unknown_old_runner_or_omitted_dependency_is_not_accepted(self) -> None:
        for change in ("runner", "omit"):
            old, current = states()
            if change == "runner":
                old["measurementSources"]["graphics/comp_capability_refresh.py"] = "unreviewed"
            else:
                del old["measurementSources"]["color/deadline.py"]
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                resume._source_binding(old, current)

    def test_timer_restores_hook_on_failure_and_does_not_swallow_error(self) -> None:
        self.assertIsNone(sys.getprofile())
        with self.assertRaisesRegex(ValueError, "original"):
            with phase_timings([]):
                raise ValueError("original")
        self.assertIsNone(sys.getprofile())

    def test_timer_never_replaces_an_existing_profiler(self) -> None:
        with patch("graphics.comp_capability_timing.sys.getprofile", return_value=object()):
            with self.assertRaisesRegex(RuntimeError, "existing profiler"):
                with phase_timings([]):
                    self.fail("must reject before yielding")

    def test_projection_uses_actual_remaining_duration_and_preserves_prior_wall(self) -> None:
        value = {"probes": [{"kind": "long", "elapsedMs": 46514}],
                 "plannedProbeSeconds": {"long": 13.95, "short": 2.5}}
        projected, model = projection(value, 1400, 2)
        self.assertEqual(projected, 1400 + 7 + 7.5 + 30)
        self.assertIn("output-second", model)
        value["probes"][0]["elapsedMs"] = 100000
        self.assertGreater(projection(value, 1400, 2)[0], projected)
        value["plannedProbeSeconds"]["short"] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "duration inventory"):
            projection(value, 1400, 2)


if __name__ == "__main__":
    unittest.main()
