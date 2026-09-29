"""Public retained-frame binding, actual window relay and sealing over fictional media."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _native_retained_frames_fixture import RetainedFixture, manifest
from _native_long_probe_fixture import synthetic_dependency_probe
from _native_short_pipeline_fixture import write_json
from cut_preview_io import bound_json
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.native_segments.compatibility import prepare_long_repair
from studio.native_segments.dependency import inventory
from studio.native_segments.frame_capture import bind_frame_reuse, require_frame_reuse, finish_frame_capture, read_frame_plan
from studio.native_segments.frame_reuse import baseline_capture, frame_reuse_plan
from studio.native_segments import owners, worker


class LongFrameCaptureTests(unittest.TestCase):
    """Media is fictional; request history, compatibility, owner seals and reader paths are real."""

    def setUp(self) -> None:
        """Use isolated registration histories and an original sealed retained capture."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory',
                                side_effect=lambda request: self.base / 'history' / Path(request['project']).name))
        self.fixture = RetainedFixture(self.base)
        self.phase = self.fixture.phase

    def test_binding_freezes_exact_capture_plan_and_original_pins(self) -> None:
        """No capture starts from a merely proposed plan without its complete admitted lineage."""
        request = self.fixture.child()
        with self.assertRaisesRegex(ValueError, 'published retained frame plan'):
            require_frame_reuse(request, self.phase)
        bind_frame_reuse(request)
        require_frame_reuse(request, self.phase)
        plan = read_frame_plan(request, self.phase)
        self.assertGreater(len(plan['copyFrames']), 20)
        self.assertNotIn('requiredPins', plan)
        self.assertTrue(all(request['pins'][file] == sha
                            for file, sha in frame_reuse_plan(request, self.phase)['requiredPins'].items()))

    def test_actual_capture_proof_is_published_only_after_exact_comparison(self) -> None:
        """The owner records current copied/checked frames; no independent editorial approval is minted."""
        request = self.fixture.child()
        bind_frame_reuse(request)
        plan = read_frame_plan(request, self.phase)
        pin = manifest(request, 'actual-current', plan)
        capture = bound_json(Path(pin['path']))
        receipt = {'retainedFrames': pin, 'window': request['revision']['renderWindows'][0],
                   'frameSha256': [row['sha256'] for row in capture['frames']]}
        result = finish_frame_capture(request, self.phase, receipt)
        proof = result['retainedFrameProof']
        value = bound_json(Path(proof['path']), proof['sha256'])
        self.assertTrue(value['passed'])
        self.assertFalse(value['editorialApproval'])
        self.assertEqual(value['copiedFrames'], plan['copyFrames'])
        receipt['frameSha256'][0] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'encoded window inventory'):
            finish_frame_capture(request, self.phase, receipt)

    def unchanged_child(self) -> dict:
        """Prepare and register a genuine unchanged-project full-window donor relation."""
        original = self.fixture.request
        project, output = self.base / 'relay-project', self.base / 'relay-attempt'
        shutil.copytree(original['project'], project)
        pins = {**original['sectionImplementationPins'],
                **{str(project / name): sha for name, sha in inventory(project).items()}}
        current = {**original, 'project': str(project), 'output': str(output), 'pins': pins}
        current = prepare_long_repair(current, Path(original['output']))
        output.mkdir()
        self.fixture.f.write_request(current)
        register_attempt(current)
        return current

    def complete_relay(self, request: dict) -> dict:
        """Execute actual whole-window reuse and seal it after a synthetic successful owner."""
        with patch.object(worker, 'section_audio', return_value={}):
            with patch('studio.native_segments.probe.execute_dependency_probe', side_effect=synthetic_dependency_probe):
                value = worker.execute_segment(request, self.phase)
        root = Path(request['output'])
        pins = {**request['pins'], str(root / 'export-request.json'): digest(root / 'export-request.json')}
        record = self.fixture.f.owner_record(request, pins, owners.STATUS, str(root / f'{self.phase}.json'))
        write_json(root / f'{self.phase}.render.json', record)
        owners.seal_window(SimpleNamespace(root=root, request=request, evidence={}), self.phase, self.phase)
        return value

    def test_full_window_relay_preserves_original_capture_for_next_local_repair(self) -> None:
        """A copied codec window can later donate original captures without flattened false paths."""
        request = self.unchanged_child()
        value = self.complete_relay(request)
        self.assertNotIn('retainedFrames', value)
        self.assertIn('retainedCaptureDonor', value)
        self.assertEqual(list(Path(request['output']).rglob('frame_*.jpg')), [])
        baseline, pins = baseline_capture(request, self.phase)
        self.assertEqual(baseline['manifest'], owners.current_window(self.fixture.request, self.phase)['retainedFrames'])
        self.assertIn(str(Path(request['output']) / f'{self.phase}-stage.json'), pins)
        child = self.fixture.child(parent=request)
        plan = frame_reuse_plan(child, self.phase)
        self.assertEqual(plan['mode'], 'retained-frames')
        self.assertGreater(len(plan['copyFrames']), 20)
        Path(baseline['frames'][0]['path']).write_bytes(b'TEST corrupted original')
        with self.assertRaises(ValueError):
            baseline_capture(request, self.phase)

    def test_exact_restore_keeps_original_inventory_without_recopying_jpegs(self) -> None:
        """Cold baseline reads use the original sealed request, not the restored output directory."""
        original = self.fixture.request
        request = {**original, 'output': str(self.base / 'exact-resume'), 'pins': dict(original['pins']),
                   'sectionAttemptSequence': 2}
        owners.bind_window_recovery(request, [Path(original['output'])])
        root = Path(request['output'])
        root.mkdir()
        self.fixture.f.write_request(request)
        register_attempt(request)
        pipeline = SimpleNamespace(root=root, request=request, evidence={}, stages=[])
        self.assertTrue(owners.restore_window(pipeline, self.phase))
        baseline, _pins = baseline_capture(request, self.phase)
        self.assertTrue(Path(baseline['manifest']['path']).is_relative_to(Path(original['output'])))
        self.assertEqual(list(root.rglob('frame_*.jpg')), [])
