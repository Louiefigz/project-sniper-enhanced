"""Actual Node pure boundary calls; no decoder, runtime probe or media IO."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from _grade_observation_v2_fixture import v2_request
from color.grade_observation_profile import V1, V2

WORKER = Path(__file__).resolve().parents[1] / "headless/grade_observation_worker.js"
SCRIPT = """
const fs = require('node:fs'), worker = require(process.argv[1]);
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const config = worker.validate(request.request);
  if (request.probe) worker.requireProbeClass(request.probe, request.request);
  process.stdout.write(JSON.stringify({ok:true,evidence:worker.evidence(config),
    args:worker.decodeArgs(config),maxSourceBytes:config.maxSourceBytes}));
} catch(error) { process.stdout.write(JSON.stringify({ok:false,error:String(error.message)})); }
"""


def node_check(request: dict, probe: dict | None = None) -> dict:
    """Invoke only exported pure guards, with a three-second outer bound."""
    output = subprocess.run(["node", "-e", SCRIPT, str(WORKER)],
        input=json.dumps({"request": request, "probe": probe}), text=True,
        capture_output=True, check=True, timeout=3)
    if output.stderr:
        raise AssertionError(output.stderr)
    return json.loads(output.stdout)


def probe() -> dict:
    """C0679-shaped source metadata only, not a decoded source observation."""
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 3840,
        "height": 2160, "nb_frames": "20004", "pix_fmt": "yuv420p", "color_range": "tv",
        "color_space": "bt709", "color_transfer": "iec61966-2-4", "color_primaries": "bt709",
        "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001"}]}


class GradeObservationV2WorkerTests(unittest.TestCase):
    """Mirrored Python/JS limits cannot drift or permit a historical upgrade."""

    def test_explicit_v2_threads_limits_and_original_transfer_class(self) -> None:
        result = node_check(v2_request(20004), probe())
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"], V2.evidence())
        self.assertEqual(result["args"][5], "4")
        self.assertEqual(result["maxSourceBytes"], V2.max_source_bytes)
        legacy = {"sourceSha256": "a" * 64, "frameCount": 180, "timeoutSeconds": 120}
        old = node_check(legacy)
        self.assertTrue(old["ok"])
        self.assertEqual(old["args"][5], "1")
        self.assertEqual(old["evidence"], {})
        self.assertEqual(old["maxSourceBytes"], V1.max_source_bytes)

    def test_request_coercion_or_extra_settings_reject_before_any_io(self) -> None:
        for key, value in (("schemaVersion", True), ("schemaVersion", 1), ("profile", None),
                           ("frameCount", 24001), ("timeoutSeconds", 1201),
                           ("sourceSha256", ["a" * 64]), ("decoderThreads", 4)):
            with self.subTest(key=key):
                self.assertFalse(node_check({**v2_request(), key: value})["ok"])
        legacy = {"sourceSha256": "a" * 64, "frameCount": 1, "timeoutSeconds": 121}
        self.assertFalse(node_check(legacy)["ok"])

    def test_unsupported_probe_cannot_reach_full_decode(self) -> None:
        cases = (("width", 3842), ("width", 3839), ("height", 2162),
                 ("nb_frames", "20003"), ("codec_name", "hevc"), ("color_transfer", "bt709"),
                 ("color_range", "pc"), ("tags", {"rotate": "0"}),
                 ("avg_frame_rate", "24/1"), ("side_data_list", [{"side_data_type": "Display Matrix"}]))
        for key, value in cases:
            value_probe = probe()
            value_probe["streams"][0][key] = value
            with self.subTest(key=key):
                self.assertFalse(node_check(v2_request(20004), value_probe)["ok"])


if __name__ == "__main__":
    unittest.main()
