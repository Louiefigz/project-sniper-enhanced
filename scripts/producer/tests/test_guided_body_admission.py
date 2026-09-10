"""Native graph admission boundaries, no media/template renderer or approvals."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from cut_preview_io import digest
from guided_body_admission import admit_body_workload
from test_guided_body_frames import fixture, rebind


def _packet(count: int, canvas: tuple[int, int]) -> tuple:
    inputs = fixture(count)
    inputs.documents["candidatePlan"]["target"].update(width=canvas[0], height=canvas[1])
    rebind(inputs)
    inputs.documents["frameBindings"]["targetHash"] = digest(inputs.documents["authority"]["target"])
    return inputs, {"fullProgram": {"base": {"sizeBytes": 4}}}


class GuidedBodyAdmissionTests(unittest.TestCase):
    def test_full_native_surface_bound_is31_not32_graphics_at1080p(self) -> None:
        self.assertEqual(admit_body_workload(*_packet(31, (1920, 1080)))["fullGraphics"], 31)
        with self.assertRaisesRegex(RuntimeError, "32 full graphics.*no graphics were rendered"):
            admit_body_workload(*_packet(32, (1920, 1080)))

    def test_4k_native_graph_accepts7_rejects8_without_dropping_rows(self) -> None:
        self.assertEqual(admit_body_workload(*_packet(7, (3840, 2160)))["fullGraphics"], 7)
        with self.assertRaisesRegex(RuntimeError, "8 full graphics.*no graphics were rendered"):
            admit_body_workload(*_packet(8, (3840, 2160)))

    def test_frame_range_and_base_byte_class_fail_before_any_seal(self) -> None:
        inputs, original = _packet(1, (1920, 1080))
        original["fullProgram"]["base"]["sizeBytes"] = 2 * 1024 ** 3 + 1
        with self.assertRaisesRegex(RuntimeError, "2GiB"):
            admit_body_workload(inputs, original)
        original["fullProgram"]["base"]["sizeBytes"] = 4
        inputs.documents["authority"]["review"]["endFrameExclusive"] = 8000
        with self.assertRaises(RuntimeError):
            admit_body_workload(inputs, original)

    def test_effective_projection_cannot_add_unreviewed_geometry(self) -> None:
        with patch("guided_body_admission.apply_exit_on_cut", return_value=([{"TEST": "projected"}], 0)):
            with self.assertRaisesRegex(RuntimeError, "effective graphics projection"):
                admit_body_workload(*_packet(1, (1920, 1080)))


if __name__ == "__main__":
    unittest.main()
