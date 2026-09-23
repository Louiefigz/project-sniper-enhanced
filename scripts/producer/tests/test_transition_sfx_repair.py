"""Retired transition repair refuses before probing or materializing media."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from motion.transition_sfx_repair import TransitionSfxRepairRequest, repair_transition_sfx
from motion.transitions import apply_transitions


class TransitionSfxRepairTests(unittest.TestCase):
    def test_retired_sfx_and_picture_edits_never_probe_mux_or_write(self) -> None:
        for kind in ("white-flash", "light-leak", "zoom-pull"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                before = [{"outTime": 1, "kind": kind, "sfx": False}]
                after = [{"outTime": 1, "kind": kind, "sfx": True}]
                request = TransitionSfxRepairRequest(
                    "/absent-program.mp4", "/absent-picture.mp4", before,
                    after, str(root / "repaired.mp4"))
                with mock.patch("motion.transition_sfx_repair.probe_duration") as probe, \
                        mock.patch("motion.transition_sfx_repair.run_ff") as run:
                    with self.assertRaisesRegex(ValueError, "retired"):
                        repair_transition_sfx(request)
                    probe.assert_not_called()
                    run.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_empty_previous_selection_rejects_before_probe(self) -> None:
        request = TransitionSfxRepairRequest("/absent", "/absent", [],
            [{"outTime": 1, "kind": "white-flash", "sfx": True}], "/absent")
        with mock.patch("motion.transition_sfx_repair.probe_duration") as probe:
            with self.assertRaisesRegex(ValueError, "non-empty"):
                repair_transition_sfx(request)
            probe.assert_not_called()

    def test_original_transition_renderer_cannot_restore_retired_preset(self) -> None:
        with self.assertRaisesRegex(ValueError, "retired"):
            apply_transitions("/absent", [{"outTime": 1, "kind": "white-flash"}], "/absent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
