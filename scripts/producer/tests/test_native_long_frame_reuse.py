"""Real lineage/seals with fictional JPEG bytes; no pixel or render qualification."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_retained_frames_fixture import RetainedFixture, manifest
from _native_short_pipeline_fixture import write_json
from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments.frame_reuse import frame_reuse_plan, validate_frame_reuse, validate_frame_capture


class LongFrameReuseTests(unittest.TestCase):
    """Capture reduction never changes the encoder window or trusts unsealed screenshots."""

    def setUp(self) -> None:
        """Use isolated actual per-project registration histories."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory',
                                side_effect=lambda request: self.base / 'history' / Path(request['project']).name))

    def admitted(self) -> tuple[dict, dict]:
        """Freeze the helper's exact required pins as a future public admission would."""
        self.fixture = RetainedFixture(self.base)
        request = self.fixture.child()
        plan = frame_reuse_plan(request, self.fixture.phase)
        request['pins'].update(plan['requiredPins'])
        validate_frame_reuse(request, self.fixture.phase, plan)
        return request, plan

    def test_local_dirty_window_preserves_unchanged_frames_and_recaptures_checks(self) -> None:
        """B's local edit retains A/C screenshots while requiring one full 75-frame encode."""
        request, plan = self.admitted()
        self.assertEqual(plan['frameRange'], [0, 75])
        self.assertEqual(plan['mode'], 'retained-frames')
        self.assertTrue(set(range(25, 50)) <= set(plan['captureFrames']))
        self.assertGreater(len(plan['copyFrames']), 20)
        self.assertFalse(set(plan['copyFrames']) & set(range(25, 50)))
        self.assertTrue({0, 24, 50, 74} <= set(plan['checkFrames']))
        pin = manifest(request, 'capture-current', plan)
        value = bound_json(Path(pin['path']))
        row = value['frames'][30]
        Path(row['path']).write_bytes(b'TEST repaired B pixels')
        row.update(sha256=digest(Path(row['path'])), bytes=Path(row['path']).stat().st_size)
        write_json(Path(pin['path']), value)
        pin['sha256'] = digest(Path(pin['path']))
        proof = validate_frame_capture(request, self.fixture.phase, plan, pin)
        self.assertTrue(proof['passed'])
        self.assertFalse(proof['editorialApproval'])
        self.assertEqual(proof['runtimeQualification'], 'not-established')

    def test_current_unchanged_probe_mismatch_refuses_even_with_updated_manifest_hash(self) -> None:
        """Current recapture bytes are compared with the sealed donor, not a self-consistent label."""
        request, plan = self.admitted()
        pin = manifest(request, 'capture-current', plan)
        value = bound_json(Path(pin['path']))
        row = value['frames'][plan['checkFrames'][0]]
        Path(row['path']).write_bytes(b'TEST unexpected current pixels')
        row.update(sha256=digest(Path(row['path'])), bytes=Path(row['path']).stat().st_size)
        write_json(Path(pin['path']), value)
        pin['sha256'] = digest(Path(pin['path']))
        with self.assertRaisesRegex(ValueError, 'differs from original pixels'):
            validate_frame_capture(request, self.fixture.phase, plan, pin)

    def test_missing_historical_baseline_is_explicit_full_capture(self) -> None:
        """Older valid section receipts without retained JPEGs remain renderable."""
        fixture = RetainedFixture(self.base, retained=False)
        plan = frame_reuse_plan(fixture.child(), fixture.phase)
        self.assertEqual(plan['mode'], 'full-capture')
        self.assertIn('no sealed retained', plan['reason'])
        self.assertEqual(plan['captureFrames'], list(range(75)))

    def test_corrupt_present_baseline_hard_refuses(self) -> None:
        """Baseline corruption cannot silently become an unobserved full-capture fallback."""
        request, plan = self.admitted()
        Path(plan['baseline']['frames'][0]['path']).write_bytes(b'TEST corrupt original')
        with self.assertRaises((ValueError, RuntimeError)):
            frame_reuse_plan(request, self.fixture.phase)

    def test_shared_change_widens_capture_to_every_frame(self) -> None:
        """An actual shared style mutation cannot preserve apparently unchanged JPEG ranges."""
        fixture = RetainedFixture(self.base)
        plan = frame_reuse_plan(fixture.child(global_change=True), fixture.phase)
        self.assertEqual(plan['mode'], 'full-capture')
        self.assertEqual(plan['copyFrames'], [])
        self.assertEqual(plan['captureFrames'], list(range(75)))

    def test_unpinned_or_mutated_generation_plan_refuses(self) -> None:
        """Consumption requires the exact previously admitted donor and current generation."""
        request, plan = self.admitted()
        request['pins'].pop(plan['baseline']['seal']['path'])
        with self.assertRaisesRegex(ValueError, 'was not admitted'):
            validate_frame_reuse(request, self.fixture.phase, plan)
        request['pins'].update(plan['requiredPins'])
        plan['copyFrames'].append(30)
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            validate_frame_reuse(request, self.fixture.phase, plan)

    def test_retained_frame_cannot_be_reported_as_captured_or_skip_disposal(self) -> None:
        """Session coverage and requested copy/capture partition are exact independently."""
        request, plan = self.admitted()
        pin = manifest(request, 'capture-current', plan)
        value = bound_json(Path(pin['path']))
        value['sessions'][0]['serverClosed'] = False
        write_json(Path(pin['path']), value)
        pin['sha256'] = digest(Path(pin['path']))
        with self.assertRaisesRegex(ValueError, 'dispose cleanly'):
            validate_frame_capture(request, self.fixture.phase, plan, pin)

    def test_second_generation_reopens_original_capture_comparison_chain(self) -> None:
        """A reused JPEG may donate again only with the entire original comparison still intact."""
        request, plan = self.admitted()
        self.fixture.complete(request, plan)
        second = self.fixture.child(parent=request)
        next_plan = frame_reuse_plan(second, self.fixture.phase)
        self.assertEqual(next_plan['mode'], 'retained-frames')
        self.assertEqual(next_plan['window']['generation'], 3)
        proof = Path(request['output']) / 'capture-current' / 'retained-proof.json'
        proof.write_text('{}')
        with self.assertRaises((ValueError, RuntimeError)):
            frame_reuse_plan(second, self.fixture.phase)

    def test_second_generation_refuses_retained_pixels_without_prior_comparison(self) -> None:
        """A cleanup seal alone cannot assert that previously copied JPEGs were compatible."""
        request, plan = self.admitted()
        self.fixture.complete(request, plan, include_proof=False)
        second = self.fixture.child(parent=request)
        with self.assertRaisesRegex(ValueError, 'sealed comparison authority'):
            frame_reuse_plan(second, self.fixture.phase)


if __name__ == '__main__':
    unittest.main()
