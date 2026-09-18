#!/usr/bin/env python3
"""Source-binding tests for qualified visual-state receipts."""

from __future__ import annotations

import copy
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest_admission_contract import canonical_bytes
from qualification_visual_state import build_receipt, verify_receipt


def _row() -> dict:
    return {
        "outStart": 0.0,
        "outEnd": 12.0,
        "state": "talking-head",
        "confidence": "high",
        "faceBBoxNorm": [0.4, 0.2, 0.2, 0.3],
        "signals": {
            "faceRate": 1.0,
            "faceAreaFrac": 0.06,
            "busyFrac": 0.1,
            "samples": 6,
        },
    }


def _inputs(root: Path) -> tuple[Path, Path, Path]:
    media = root / "qualified.mp4"
    media.write_bytes(b"qualified-media")
    payload = media.read_bytes()
    source = {
        "id": "raw-1",
        "role": "primary",
        "path": str(media),
        "sourceSha256": hashlib.sha256(payload).hexdigest(),
        "sourceSizeBytes": len(payload),
    }
    manifest = root / "asset_manifest.json"
    manifest.write_bytes(canonical_bytes({"sources": [source]}))
    zones = root / "zones.json"
    zones.write_bytes(canonical_bytes([{"outStart": 0, "outEnd": 12}]))
    return media, manifest, zones


class QualificationVisualStateTests(unittest.TestCase):
    def test_receipt_binds_source_rows_implementation_and_read_cost(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _media, manifest, zones = _inputs(root)
            with patch(
                "qualification_visual_state._classify_zones",
                return_value=[_row()],
            ):
                receipt = build_receipt(str(manifest), str(zones))
            output = root / "visual-state.json"
            output.write_bytes(canonical_bytes(receipt))
            verified = verify_receipt(str(output))
            self.assertEqual(verified, receipt)
            self.assertEqual(
                receipt["measurement"]["rowsSha256"],
                hashlib.sha256(canonical_bytes([_row()])).hexdigest(),
            )
            self.assertEqual(
                receipt["readCost"]["measurementFullSourceByteReads"], 1
            )
            self.assertEqual(
                receipt["readCost"]["verificationFullSourceByteReadsPerCall"], 1
            )

    def test_source_change_during_measurement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media, manifest, zones = _inputs(root)

            def mutate(_path, _zones):
                media.write_bytes(b"changed-media")
                return [_row()]

            with patch(
                "qualification_visual_state._classify_zones",
                side_effect=mutate,
            ), self.assertRaisesRegex(RuntimeError, "changed during"):
                build_receipt(str(manifest), str(zones))

    def test_tampered_measurement_or_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media, manifest, zones = _inputs(root)
            with patch(
                "qualification_visual_state._classify_zones",
                return_value=[_row()],
            ):
                receipt = build_receipt(str(manifest), str(zones))
            for target in ("measurement", "source"):
                candidate = copy.deepcopy(receipt)
                if target == "measurement":
                    candidate["measurement"]["rows"][0]["state"] = "mixed"
                else:
                    candidate["source"]["sha256"] = "0" * 64
                output = root / f"{target}.json"
                output.write_bytes(canonical_bytes(candidate))
                with self.subTest(target=target), self.assertRaises(RuntimeError):
                    verify_receipt(str(output))
            self.assertEqual(media.read_bytes(), b"qualified-media")


if __name__ == "__main__":
    unittest.main()
