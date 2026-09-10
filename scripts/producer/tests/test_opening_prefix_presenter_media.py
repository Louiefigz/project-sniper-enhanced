"""Real tiny shared presenter prefix/encode; no admission or profile qualification."""
from __future__ import annotations

import time
import unittest
from pathlib import Path

from _opening_prefix_presenter_media_fixture import PresenterPrefixMediaFixture
from test_opening_prefix_contract import held


class PresenterPrefixMediaTests(unittest.TestCase):
    """Actual PNG/video observations flow into the oracle and one actual picture encode."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start one original cohort clock before all setup; retain the tiny source tree."""
        cls.fixture = PresenterPrefixMediaFixture()

    def _check(self, name: str) -> None:
        """Compare encoded full-frame RGB with the ordinary exact graph/encoder."""
        started = time.monotonic()
        fixture = self.fixture
        try:
            result, job = fixture.compose(name)
            self.assertEqual(result["schemaVersion"], 2)
            self.assertEqual(result["kind"], "verified-presenter-prefix-private-picture-composition")
            proof = result["prefixOracle"]
            self.assertEqual(proof["schemaVersion"], 2)
            self.assertEqual(proof["layerPolicy"]["fullPresenterWindows"], 2)
            self.assertEqual(proof["layerPolicy"]["openingPresenterWindows"], 1)
            self.assertEqual(proof["graphicWorkload"]["fullGraphInputPixels"], 64 * 36 * 4)
            self.assertEqual(proof["graphicWorkload"]["openingGraphInputPixels"], 64 * 36 * 3)
            self.assertTrue(proof["comparison"]["core"]["exactPreencodePixels"])
            self.assertTrue(proof["comparison"]["review"]["exactPreencodePixels"])
            self.assertFalse(result["deliveryApproved"])
            self.assertFalse(result["audioCompared"])
            self.assertFalse(result["outputDecoded"])
            self.assertEqual(result["output"]["sha256"], held(Path(job.output_path)).sha256)
            reference = fixture.reference(name, job)
            pixels = fixture.frames(name + "-final-allframes", Path(job.output_path))
            self.assertEqual(pixels, fixture.frames(name + "-reference-allframes", reference))
            fixture.results.append({"case": name, "elapsedSeconds": time.monotonic() - started,
                "compositionMs": result["elapsedMs"], "oracleTimingMs": proof["timingMs"],
                "full24FrameRgbIdentical": True, "schema2": True, "originalObservationsReused": True})
            fixture.record("passed")
        except BaseException as error:
            fixture.record("failed", f"{type(error).__name__}: {error}")
            raise

    def test_still_crossing_future_windows_and_caption_tail(self) -> None:
        """Actual PNG is converted once per window, never treated as a CFR video."""
        self._check("still")

    def test_video_crossing_future_windows_and_caption_tail(self) -> None:
        """Actual NTSC video keeps selected frames and the original full graph clock."""
        self._check("video")


if __name__ == "__main__":
    unittest.main(verbosity=2)
