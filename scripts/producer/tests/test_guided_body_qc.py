"""Readback coverage and after-observation races, with TEST bytes not media."""
from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audit.audit_frames import plan_frames
from cut_preview_io import write_new
from guided_body_qc import (_BASE_CHECKS, _REQUIRED_SUPPORT, _graphic_checks, artifact_reference,
    check_audit_coverage, observe_body_support, verify_body_support)
from guided_body_read import _unchanged
from guided_body_result import verify_body_media_files


def _plan() -> dict:
    """TEST plan metadata, not an admitted or executable plan."""
    return {"target": {"mode": "longform", "treatment": "clean-cut"},
        "cutTrack": [{"source": "TEST", "start": 0, "end": 4}], "graphicsTrack": []}


def _report() -> dict:
    """Shape fixture only; names are not evidence these actual checks executed."""
    checks = [{"name": name, "status": "pass", "measured": "TEST", "detail": "TEST"}
              for name in sorted(_BASE_CHECKS)]
    return {"checks": checks, "frames": [asdict(row) for row in plan_frames(_plan(), 4)],
            "counts": {"pass": len(checks), "warn": 0, "fail": 0}, "overall": "pass"}


class GuidedBodyQcTests(unittest.TestCase):
    def test_existing_all_row_and_frame_planner_shape_is_required(self) -> None:
        check_audit_coverage(_report(), _plan(), 4)
        report = _report()
        report["checks"] = [{"name": "TEST-only-single-check", "status": "pass", "measured": "TEST", "detail": "TEST"}]
        report["counts"]["pass"] = 1
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            check_audit_coverage(report, _plan(), 4)

    def test_missing_duplicate_failed_check_or_forged_counts_reject(self) -> None:
        mutations = (lambda row: row["checks"].pop(), lambda row: row["checks"].append(row["checks"][0]),
            lambda row: row["checks"][0].update(status="fail"), lambda row: row["counts"].update(warn=1))
        for mutation in mutations:
            report = _report()
            mutation(report)
            with self.assertRaises(RuntimeError):
                check_audit_coverage(report, _plan(), 4)

    def test_missing_shifted_foreign_or_reordered_frame_reject(self) -> None:
        mutations = (lambda row: row["frames"].pop(), lambda row: row["frames"][0].update(timestamp=3),
            lambda row: row["frames"][0].update(kind="TEST-foreign"), lambda row: row["frames"].reverse())
        for mutation in mutations:
            report = _report()
            mutation(report)
            with self.assertRaises(RuntimeError):
                check_audit_coverage(report, _plan(), 4)

    def test_whole_body_graphics_need_every_presence_and_declared_contrast(self) -> None:
        plan, report = _plan(), _report()
        plan["graphicsTrack"] = [{"kind": "statement-card", "outStart": 1, "outEnd": 3,
                                   "spec": {"text": "TEST", "accent": "#7FB4FF"}}]
        report["frames"] = [asdict(row) for row in plan_frames(plan, 4)]
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            check_audit_coverage(report, plan, 4)

    def test_own_screen_accent_skip_matches_actual_audit_not_a_new_required_check(self) -> None:
        from audit.audit_composite_visual import _accent_result
        graphic = {"kind": "statement-card", "anchor": "own-screen", "outStart": 1, "outEnd": 3,
                   "spec": {"text": "TEST", "accent": "#7FB4FF"}}
        plan = _plan()
        plan["graphicsTrack"] = [graphic]
        self.assertIsNone(_accent_result(0, graphic, []))
        self.assertNotIn("graphic_composite_0_contrast", _graphic_checks(plan))
        self.assertIn("graphic_composite_0_presence", _graphic_checks(plan))

    def test_warnings_are_preserved_not_promoted_to_clean_pass(self) -> None:
        report = _report()
        report["checks"][0]["status"] = "warn"
        report["counts"]["pass"] -= 1
        report["counts"]["warn"] = 1
        with self.assertRaisesRegex(RuntimeError, "verdict"):
            check_audit_coverage(report, _plan(), 4)
        report["overall"] = "warn"
        check_audit_coverage(report, _plan(), 4)

    def _support(self, root: Path) -> tuple[list[dict], dict]:
        candidate = root / "body-candidate"
        candidate.mkdir(mode=0o700)
        stage = candidate / ".source-assembly-v2-TEST"
        stage.mkdir(mode=0o700)
        for name in _REQUIRED_SUPPORT:
            (candidate / name).write_bytes(b"TEST only, no media")
        write_new(stage / "edit_plan.json", _plan())
        composition = {"outputPath": str(stage / "final.mp4")}
        return observe_body_support(root, _plan(), composition), composition

    def test_missing_required_support_or_added_optional_file_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rows, _composition = self._support(root)
            verify_body_support(root, rows)
            missing = copy.deepcopy(rows)
            missing[0]["artifact"] = None
            with self.assertRaisesRegex(RuntimeError, "required support"):
                verify_body_support(root, missing)
            (root / "body-candidate/graphics_placements.json").write_bytes(b"TEST unexpected")
            with self.assertRaisesRegex(RuntimeError, "appeared"):
                verify_body_support(root, rows)
            (root / "body-candidate/graphics_placements.json").unlink()
            (root / "body-candidate/cut_delivery.v1.json").unlink()
            with self.assertRaises((OSError, RuntimeError)):
                verify_body_support(root, rows)

    def test_final_source_recheck_racing_cut_support_cannot_return_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rows, _composition = self._support(root)
            file = root / "TEST-artifact"
            file.write_bytes(b"TEST not final video")
            reference = artifact_reference(file)
            media = {"picture": reference, "final": reference, "programDelivery": reference,
                     "audit": {**reference, "frames": []}, "support": rows}
            verify_body_media_files(root, media)
            def mutate() -> None:
                (root / "body-candidate/cut_delivery.v1.json").write_bytes(b"TEST changed after QC")
            work = SimpleNamespace(control=SimpleNamespace(root=root), revalidate=mutate, guard=lambda: None)
            record = {"media": media}
            with patch("guided_body_read.read_body_graphics"), patch("guided_body_read._screen"), \
                    patch("guided_body_read.read_body_record", return_value=record):
                with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                    _unchanged(work, record, object())


if __name__ == "__main__":
    unittest.main()
