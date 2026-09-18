"""Released-rate HyperFrames matrix contract tests."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from graphics.comp_rate_matrix import (
    PROBE_FRAMES,
    ProbeRequest,
    _probe_stream,
    _temp_name,
)
from graphics.comp_rate_artifact import (
    _receipt_hash,
    current_tool_receipts,
    load_rate_matrix,
    validate_rate_matrix,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / (
    "docs/producer/command-driven-editing/contracts/"
    "hyperframes-rate-matrix-v1.json"
)


class CompRateMatrixTests(unittest.TestCase):
    def test_temp_identity_binds_kind_and_exact_rate(self) -> None:
        first = ProbeRequest("color-wash", "<html>", "30000/1001", "/tmp")
        second = ProbeRequest("color-wash", "<html>", "30", "/tmp")
        self.assertNotEqual(_temp_name(first), _temp_name(second))
        self.assertTrue(_temp_name(first).startswith("_gs-rate-"))

    def test_stream_probe_requires_both_exact_rates_and_frame_count(self) -> None:
        stream = {
            "codec_name": "png", "pix_fmt": "rgba",
            "width": 1080, "height": 1920,
            "r_frame_rate": "30000/1001",
            "avg_frame_rate": "30000/1001",
            "nb_read_frames": str(PROBE_FRAMES),
        }
        completed = type("Completed", (), {
            "returncode": 0, "stdout": json.dumps({"streams": [stream]}),
            "stderr": "",
        })()
        with patch("graphics.comp_rate_matrix.subprocess.run",
                   return_value=completed):
            parsed = _probe_stream(
                "/tmp/probe.mov", "30000/1001", {"ffprobe": "ffprobe"})
        self.assertEqual(
            Fraction(parsed["avg_frame_rate"]), Fraction(30_000, 1_001))
        for key, value in (
                ("r_frame_rate", "30/1"),
                ("nb_read_frames", str(PROBE_FRAMES + 1))):
            bad = {**stream, key: value}
            completed.stdout = json.dumps({"streams": [bad]})
            with self.subTest(key=key), patch(
                    "graphics.comp_rate_matrix.subprocess.run",
                    return_value=completed), self.assertRaises(RuntimeError):
                _probe_stream(
                    "/tmp/probe.mov", "30000/1001",
                    {"ffprobe": "ffprobe"})

    def test_source_has_no_persistent_probe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(list(Path(raw).iterdir()), [])

    def test_retained_cross_product_is_fresh(self) -> None:
        value, issue = load_rate_matrix(str(ARTIFACT))
        self.assertEqual(issue, "")
        validate_document("hyperframes-rate-matrix-v1.schema.json", value)
        self.assertEqual(len(value["probes"]), 46 * 8)
        self.assertEqual(
            value["receiptHash"],
            "8d2143163c3c2c45666e72a73af61f56f6ccb21b94fc297b57d2e5cdadf8f77b",
        )

    def test_stale_source_tool_and_tampered_row_fail_closed(self) -> None:
        original = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        tools = current_tool_receipts()
        mutations = (
            ("sourceDigest", lambda row: row.update(sourceDigest="0" * 64)),
            ("tool", lambda row: row["tools"]["node"].update(sha256="0" * 64)),
            ("probe", lambda row: row["probes"][0]["stream"].update(
                avg_frame_rate="30/1")),
            ("media", lambda row: row["probes"][0].update(
                mediaSha256="f" * 64)),
            ("unknown", lambda row: row.update(unsupported=True)),
        )
        for label, mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            value["receiptHash"] = _receipt_hash(value)
            with self.subTest(label=label):
                self.assertNotEqual(validate_rate_matrix(value, tools), "")
        with self.assertRaises(SchemaValidationError):
            validate_document(
                "hyperframes-rate-matrix-v1.schema.json",
                {**original, "unsupported": True},
            )


if __name__ == "__main__":
    unittest.main()
