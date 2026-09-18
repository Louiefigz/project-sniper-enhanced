"""Real-media checks for picture-preserving transition SFX repair."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from current_render_oracle import observe, prove
from motion.transition_sfx_repair import (
    TransitionSfxRepairRequest,
    repair_transition_sfx,
)
from motion.transitions import apply_transitions
from tests.p4_exit_media import ProgramSpec, make_program, packet_hash

HAVE_TOOLS = all(shutil.which(name) for name in ("ffmpeg", "ffprobe"))


@unittest.skipUnless(HAVE_TOOLS, "ffmpeg and ffprobe required")
class TransitionSfxRepairTests(unittest.TestCase):
    def test_sound_only_repair_reuses_picture_and_matches_forced_control(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="transition-sfx-test-") as raw:
            root = Path(raw)
            source, before = root / "source.mp4", root / "before.mp4"
            repaired, forced = root / "repaired.mp4", root / "forced.mp4"
            make_program(
                source, ProgramSpec((160, 90), 30, 2.0, pattern="flat"))
            old = [{"outTime": 1.0, "kind": "white-flash", "sfx": False}]
            new = [{"outTime": 1.0, "kind": "white-flash", "sfx": True}]
            apply_transitions(str(source), old, str(before))
            result = repair_transition_sfx(TransitionSfxRepairRequest(
                str(source), str(before), old, new, str(repaired)))
            apply_transitions(str(source), new, str(forced))
            oracle = prove(repaired, forced, root / "oracle.json")
            observed_before = observe(before)
            observed_after = observe(repaired)
            self.assertTrue(result["pictureReused"])
            self.assertEqual(packet_hash(before), packet_hash(repaired))
            self.assertEqual(
                observed_before.pictureFrameMd5Sha256,
                observed_after.pictureFrameMd5Sha256)
            self.assertNotEqual(
                observed_before.pcmSha256, observed_after.pcmSha256)
            self.assertTrue(oracle["passed"])

    def test_visual_change_is_rejected_before_mux(self) -> None:
        with tempfile.TemporaryDirectory(prefix="transition-sfx-test-") as raw:
            root = Path(raw)
            source, before = root / "source.mp4", root / "before.mp4"
            make_program(
                source, ProgramSpec((160, 90), 30, 2.0, pattern="flat"))
            old = [{"outTime": 1.0, "kind": "white-flash", "sfx": False}]
            changed = [{
                "outTime": 1.0, "kind": "light-leak", "sfx": True,
            }]
            apply_transitions(str(source), old, str(before))
            with self.assertRaisesRegex(ValueError, "cannot change"):
                repair_transition_sfx(TransitionSfxRepairRequest(
                    str(source), str(before), old, changed,
                    str(root / "repaired.mp4")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
