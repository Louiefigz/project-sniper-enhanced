"""Native color sampling rules match the retired container worker exactly.

`fixtures/color_diagnostic_worker_reference.js` is the JavaScript worker that ran in
the approved container; it is kept only as the reference implementation. Every
case runs the same input through it (node) and through the native port
(headless/color_diagnostic_native.py) and requires identical results. No decoder
runs here.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.metadata import source_metadata
from headless import color_diagnostic_native as native

WORKER = Path(__file__).resolve().parent / "fixtures" / "color_diagnostic_worker_reference.js"
from test_color_sampling import probe

_NODE = r"""
const worker = require(process.argv[1]), input = JSON.parse(process.argv[2]);
if(input.action === 'metadata') {
  process.stdout.write(JSON.stringify(input.probes.map(item => worker.supported(item))));
} else if(input.action === 'histogram') {
  const raw = Buffer.from([16,16,235,235,128,128,128,128,128,128,128,128]);
  process.stdout.write(JSON.stringify(worker.statistics(raw,4)));
} else if(input.action === 'request') {
  try { worker.validate(input.request); process.stdout.write('"accepted"'); }
  catch(error) { process.stdout.write(JSON.stringify(error.message)); }
} else if(input.action === 'hdr') {
  process.stdout.write(JSON.stringify(worker.sampleFrame({id:'one',sourceTime:70},
    input.probe,{deadline:0})));
} else if(input.action === 'frame') {
  const facts = worker.frameFacts(input.text);
  process.stdout.write(JSON.stringify({facts,supported:worker.supportedFrame(facts)}));
}
"""


def _reference(value: dict) -> object:
    """The container worker's own pure functions; no container, FFmpeg, or media read occurs."""
    result = subprocess.run(["node", "-e", _NODE, str(WORKER), json.dumps(value)],
                            capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def _native(value: dict) -> object:
    """The same action through the native port."""
    action = value["action"]
    if action == "metadata":
        return [native.supported(item) for item in value["probes"]]
    if action == "histogram":
        return native.statistics(bytes([16, 16, 235, 235, 128, 128, 128, 128, 128, 128, 128, 128]), 4)
    if action == "request":
        try:
            native.validate(value["request"])
            return "accepted"
        except native._Stop as error:
            return str(error)
    if action == "hdr":
        row = native.sample_frame(None, "/inert", {"id": "one", "sourceTime": 70}, (value["probe"], 0.0))
        return {**row, "elapsedMs": 0}
    facts = native.frame_facts(value["text"])
    return {"facts": facts, "supported": native.supported_frame(facts)}


def invoke(value: dict) -> object:
    """Both implementations; they must agree before the result is asserted."""
    reference, ported = _reference(value), _native(value)
    if isinstance(reference, dict) and "elapsedMs" in reference:
        reference = {**reference, "elapsedMs": 0}
    if reference != ported:
        raise AssertionError(f"native port disagrees with the container worker: {reference!r} != {ported!r}")
    return ported


class ColorWorkerTests(unittest.TestCase):
    def test_preconversion_frame_tags_must_be_positive_even_if_stream_is_bt709(self) -> None:
        first = '[showinfo@source @ 0x1] n: 0 pts: 2100 pts_time:70 fmt:yuv420p s:160x90\n'
        metadata = '[showinfo@source @ 0x1] color_range:tv color_space:bt709 color_primaries:bt709 color_trc:bt709\n'
        converted = '[showinfo@sample @ 0x2] n: 0 pts: 2100 pts_time:70 fmt:yuv444p s:320x180\n'
        positive = invoke({"action": "frame", "text": first + metadata + converted})
        self.assertTrue(positive["supported"])
        for changed in (metadata.replace('color_range:tv', 'color_range:pc'),
                        metadata.replace('color_trc:bt709', 'color_trc:smpte2084'),
                        metadata.replace('color_primaries:bt709', 'color_primaries:bt2020'), ''):
            value = invoke({"action": "frame", "text": first + changed + converted})
            self.assertFalse(value["supported"])
        self.assertFalse(invoke({"action": "frame", "text": first.replace('yuv420p', 'yuv420p10le') + metadata})["supported"])

    def test_worker_and_host_positive_class_rules_match(self) -> None:
        probes = [probe(), probe(color_range=None), probe(color_transfer=None),
                  probe(color_primaries=None), probe(color_space=None), probe(color_range="pc"),
                  probe(color_transfer="smpte2084"), probe(color_transfer="arib-std-b67"),
                  probe(pix_fmt="yuv420p10le"), probe(bits_per_raw_sample="10"),
                  probe(side_data_list=[{"side_data_type": "Mastering display metadata"}])]
        expected = [bool(source_metadata(item)["supportedSamplingClass"]) for item in probes]
        self.assertEqual(invoke({"action": "metadata", "probes": probes}), expected)

    def test_histogram_reports_actual_low_resolution_limit_occupancy(self) -> None:
        value = invoke({"action": "histogram"})
        self.assertEqual(value["nominalBlackFraction"], 0.5)
        self.assertEqual(value["nominalWhiteFraction"], 0.5)
        self.assertEqual(value["yMean"], 125.5)
        self.assertEqual(value["yP10"], 16)
        self.assertEqual(value["yP90"], 235)
        self.assertEqual(value["uMean"], 128)

    def test_hdr_skips_without_decoding_or_guessing_a_transform(self) -> None:
        value = invoke({"action": "hdr", "probe": probe(color_transfer="smpte2084")})
        self.assertEqual(value["status"], "skipped")
        self.assertEqual(value["error"], "UNSUPPORTED_COLOR_METADATA")
        self.assertNotIn("statistics", value)

    def test_worker_request_bounds_cannot_select_paths_commands_or_longer_deadlines(self) -> None:
        valid = {"sourceSha256": "a" * 64, "samples": [{"id": "one", "sourceTime": 70}],
                 "timeoutSeconds": 120}
        self.assertEqual(invoke({"action": "request", "request": valid}), "accepted")
        for extra in ({"input": "https://example.test/media"}, {"timeoutSeconds": 121},
                      {"samples": [{"id": "one", "sourceTime": -1}]}, {"samples": []}):
            self.assertNotEqual(invoke({"action": "request", "request": {**valid, **extra}}), "accepted")


if __name__ == "__main__":
    unittest.main()
