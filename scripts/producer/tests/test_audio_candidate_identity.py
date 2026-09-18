"""Isolated candidate mutation must not replace an already approved output."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio.audio_mix_delivery import render_qualified_mix


class AudioCandidateIdentityTests(unittest.TestCase):
    """Fault-injected identity races, not actual media measurement fixtures."""

    def test_mutation_during_measurement_preserves_final_and_its_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            output = directory / "final.mp4"
            sidecar = directory / "final.mp4.assembled.json"
            output.write_bytes(b"previous-final")
            sidecar.write_bytes(b"previous-authority")

            def render(path: str) -> dict:
                Path(path).write_bytes(b"candidate-measured")
                return {"ok": True, "stderr": ""}

            def mutate(path: str) -> dict:
                Path(path).write_bytes(b"candidate-after-measurement")
                return {"qualified": True, "lufsResidual": 0, "truePeakExcessDb": 0}

            with patch("audio.audio_mix_delivery.measure_delivery", side_effect=mutate):
                result = render_qualified_mix(str(output), render)
            self.assertFalse(result["ok"])
            self.assertFalse(result["published"])
            self.assertFalse(result["candidateStable"])
            self.assertIn("bytes changed", result["stderr"])
            self.assertEqual(output.read_bytes(), b"previous-final")
            self.assertEqual(sidecar.read_bytes(), b"previous-authority")
            self.assertEqual(Path(result["unapprovedCandidate"]).read_bytes(), b"candidate-after-measurement")

    def test_stable_candidate_records_the_actual_measured_hash(self) -> None:
        import hashlib
        with tempfile.TemporaryDirectory() as raw:
            destination = Path(raw) / "final.mp4"

            def render(path: str) -> dict:
                Path(path).write_bytes(b"stable-candidate")
                return {"ok": True, "stderr": ""}

            with patch("audio.audio_mix_delivery.measure_delivery", return_value={"qualified": True}):
                result = render_qualified_mix(str(destination), render)
            self.assertTrue(result["published"])
            self.assertEqual(result["measuredCandidateSha256"], hashlib.sha256(b"stable-candidate").hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
