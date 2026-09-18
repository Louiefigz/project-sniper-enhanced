"""Regression tests for retained codec-floor calibration source authority."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import current_render_oracle_calibrate as calibrator
from current_render_calibration_source import (
    STORAGE_CLASS,
    retain_source,
    validate_source_record_shape,
    verify_source_record,
)
from current_render_graph_contract import file_hash


class CurrentRenderCalibrationSourceTests(unittest.TestCase):
    """Prove calibration never binds authority to a trace work file."""

    def test_trace_work_rewrite_does_not_stale_retained_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            work = root / "fixture" / "work"
            work.mkdir(parents=True)
            source = work / "enhanced.mp4"
            original = b"first trace render bytes"
            source.write_bytes(original)

            facts = retain_source(source, root / "retained")
            retained = Path(facts["path"])
            source.write_bytes(b"later trace rewrote the mutable work file")

            self.assertEqual(verify_source_record(facts, root / "retained"), facts)
            self.assertEqual(retained.read_bytes(), original)
            self.assertNotEqual(file_hash(source), facts["sha256"])
            self.assertNotIn(work, retained.parents)

    def test_mutable_work_path_cannot_claim_retained_storage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source = root / "fixture" / "work" / "enhanced.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"mutable trace bytes")
            retained_root = root / "retained"
            record = {
                "path": str(source),
                "sha256": file_hash(source),
                "sizeBytes": source.stat().st_size,
                "storageClass": STORAGE_CLASS,
            }

            with self.assertRaisesRegex(RuntimeError, "not content-addressed"):
                validate_source_record_shape(record, retained_root)

    def test_retain_reuses_identity_and_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source = root / "source.mp4"
            source.write_bytes(b"stable calibration source")
            retained_root = root / "retained"
            first = retain_source(source, retained_root)
            second = retain_source(source, retained_root)
            self.assertEqual(first, second)

            retained = Path(first["path"])
            os.chmod(retained, 0o644)
            retained.write_bytes(b"tampered calibration source")
            with self.assertRaises(RuntimeError):
                verify_source_record(first, retained_root)

    def test_symlink_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source = root / "source.mp4"
            source.write_bytes(b"source")
            alias = root / "alias.mp4"
            alias.symlink_to(source)

            with self.assertRaisesRegex(RuntimeError, "non-symlink"):
                retain_source(alias, root / "retained")

    def test_calibrator_encodes_only_from_retained_path(self) -> None:
        retained = Path("/retained/sha256/aa/authority.media")
        source_record = {
            "path": str(retained), "sha256": "a" * 64,
            "sizeBytes": 10, "storageClass": STORAGE_CLASS,
        }
        pair = {
            "pictureComparison": {
                "metrics": {
                    "meanSsim": 0.999, "minimumFrameSsim": 0.998,
                },
            },
            "passed": True,
        }
        one_pair = Mock(return_value=pair)
        replacements = {
            "retain_source": Mock(return_value=source_record),
            "verify_source_record": Mock(return_value=source_record),
            "_source_files": Mock(return_value={"/source.py": "b" * 64}),
            "_runtime_facts": Mock(return_value={"ffmpeg": {}}),
            "_master_policy": Mock(return_value={"encode": {}}),
            "_one_pair": one_pair,
            "_write": Mock(),
        }

        with patch.multiple(calibrator, **replacements):
            receipt = calibrator.calibrate(
                Path("/mutable/work/enhanced.mp4"),
                Path("/receipt.json"),
                3,
            )

        self.assertEqual(receipt["source"], source_record)
        self.assertEqual(one_pair.call_count, 3)
        self.assertTrue(all(
            call.args[0] == retained for call in one_pair.call_args_list))


if __name__ == "__main__":
    unittest.main()
