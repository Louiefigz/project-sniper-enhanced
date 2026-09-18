"""Real synthetic source-clock regressions for shared mastering, not listening QC."""
from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
import unittest

from audio import master
import fingerprints
from producer_config import MASTERING_POLICY_VERSION

RATE = 48_000


def _samples(expression: str, chain: str | None = None) -> array.array:
    """Decode a generated signal through the real installed FFmpeg filter graph."""
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-f", "lavfi",
               "-i", f"aevalsrc='{expression}':s={RATE}:d=1"]
    if chain:
        command += ["-af", chain]
    result = subprocess.run(command + ["-ar", str(RATE), "-ac", "1",
                            "-c:a", "pcm_f32le", "-f", "f32le", "-"],
                            capture_output=True, check=True, timeout=20)
    return array.array("f", result.stdout)


def _center(samples: array.array, start: int, end: int) -> float:
    """Measure local energy position without treating intended gain as a mismatch."""
    energy = [float(value) ** 2 for value in samples[start:end]]
    total = math.fsum(energy)
    if total <= 1e-6:
        raise AssertionError("retained synthetic source event disappeared")
    return math.fsum((start + index) * value
                     for index, value in enumerate(energy)) / total


def _static_filter() -> str:
    """Select the production static branch using a high-LRA but unclipped input."""
    stats = {"input_i": -14, "input_tp": -8, "input_lra": 15,
             "input_thresh": -25, "target_offset": 0}
    chain, note = master.build_pass2_afilter("synthetic", None, stats, lambda _: -14)
    if "static gain" not in (note or ""):
        raise AssertionError("test did not exercise production static mastering")
    return chain


class MasterPolicyContractTests(unittest.TestCase):
    """One version must identify the same DSP and cache behavior."""

    def test_mastering_policy_is_one_shared_configuration_authority(self) -> None:
        """Cache policy and DSP policy cannot silently use different versions."""
        self.assertEqual(MASTERING_POLICY_VERSION, 3)
        self.assertEqual(master.MASTERING_POLICY_VERSION, MASTERING_POLICY_VERSION)
        self.assertEqual(fingerprints.MASTERING_POLICY_VERSION, MASTERING_POLICY_VERSION)
        self.assertEqual(fingerprints.fingerprint_record({})["masteringPolicyVersion"],
                         MASTERING_POLICY_VERSION)


@unittest.skipUnless(shutil.which("ffmpeg"), "installed FFmpeg required")
class MasterAudioClockMediaTests(unittest.TestCase):
    """An equal sample count must not hide delayed or discarded source content."""

    def test_static_master_retains_interior_source_sample_position(self) -> None:
        expression = "if(between(t,0.2,0.22),0.2*sin(2*PI*880*t),0)"
        source, output = _samples(expression), _samples(expression, _static_filter())
        self.assertEqual(len(output), len(source))
        expected = _center(source, 0, RATE)
        observed = _center(output, 0, RATE)
        self.assertLess(abs(observed - expected), 1, json.dumps({
            "sourceCenterSamples": expected, "masterCenterSamples": observed,
            "shiftMs": (observed - expected) / 48}))

    def test_static_master_flushes_retained_content_in_final_five_ms(self) -> None:
        expression = "if(gte(t,0.997),0.2*sin(2*PI*1000*t),0)"
        source, output = _samples(expression), _samples(expression, _static_filter())
        self.assertEqual(len(output), RATE)
        start = RATE - 480
        self.assertLess(abs(_center(output, start, RATE)
                            - _center(source, start, RATE)), 1)
        source_energy = math.fsum(float(value) ** 2 for value in source[start:])
        output_energy = math.fsum(float(value) ** 2 for value in output[start:])
        self.assertAlmostEqual(output_energy / source_energy, 1, delta=0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
