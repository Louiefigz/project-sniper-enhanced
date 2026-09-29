"""Real immutable stage proofs and project diffs; synthetic media, no production QC claim."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _native_long_sections_acceptance_fixture import HTML, LongSectionsFixture
from _native_long_probe_fixture import synthetic_dependency_probe
from _native_short_pipeline_fixture import write_json
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.native_long_recovery import prepare_section_recovery
from studio.native_segments.long_plan import initial_long_plan
from studio.native_segments import owners, worker
from studio.native_segments.compatibility import prepare_long_repair, compatible_donor
from studio.native_segments.dependency import inventory
from studio.native_segments.reviews import validate_review


class LongSectionCompatibilityTests(unittest.TestCase):
    """Reuse keeps original owner proof and current audio/generation authority distinct."""

    def setUp(self) -> None:
        """Create three sealed sections and distinct per-project registration histories."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory',
                                side_effect=lambda request: self.base / 'history' / Path(request['project']).name))
        self.f = LongSectionsFixture(self.base)
        (self.f.project / 'assets').mkdir()
        (self.f.project / 'assets/shared.png').write_bytes(b'TEST shared image')
        audio = self.f.project / 'program.wav'
        audio.write_bytes(b'TEST original program audio')
        document = json.loads((self.f.project / 'LONG-PROJECT.json').read_text())
        document['audio'] = {'file': 'program.wav'}
        write_json(self.f.project / 'LONG-PROJECT.json', document)
        self.f.request['pins'].update({str(self.f.project / name): sha for name, sha in inventory(self.f.project).items()})
        self.f.request['sectionImplementationPins'] = {file: sha for file, sha in self.f.request['pins'].items()
                                                     if not Path(file).is_relative_to(self.f.project)}
        self.f.write_request(self.f.request)
        register_attempt(self.f.request)
        for index in range(3):
            phase = f'segment-picture-{index}'
            self.f.write_phase(phase, self.f.root)
            self.seal(self.f.request, phase)

    def seal(self, request: dict, phase: str) -> None:
        """Use real stage sealing after an explicitly synthetic successful owner."""
        root = Path(request['output'])
        pins = {**request['pins'], str(root / 'export-request.json'): digest(root / 'export-request.json')}
        record = self.f.owner_record(request, pins, owners.STATUS, str(root / f'{phase}.json'))
        write_json(root / f'{phase}.render.json', record)
        owners.seal_window(SimpleNamespace(root=root, request=request, evidence={}), phase, phase)

    def child(self, name: str = 'child', original: dict | None = None) -> dict:
        """Copy authored bytes once; preserve the prior snapshot and all original evidence."""
        parent = original or self.f.request
        project, output = self.base / name, self.base / f'{name}-attempt'
        shutil.copytree(parent['project'], project)
        pins = dict(parent['sectionImplementationPins'])
        pins.update({str(project / item): sha for item, sha in inventory(project).items()})
        return {**parent, 'project': str(project), 'output': str(output), 'pins': pins,
                'sectionAttemptSequence': 1}

    def admit(self, request: dict, parent: dict | None = None) -> dict:
        """Refresh current authored pins, call production compatibility, and register."""
        root = Path(request['project'])
        request['pins'].update({str(root / item): sha for item, sha in inventory(root).items()})
        value = prepare_long_repair(request, Path((parent or self.f.request)['output']))
        Path(value['output']).mkdir()
        self.f.write_request(value)
        register_attempt(value)
        return value

    def current_audio(self, request: dict, window: dict, directory: Path) -> dict:
        """Substitute PCM extraction only; bytes identify the current program source."""
        file = directory / 'section-audio.wav'
        file.write_bytes(Path(request['project'], 'program.wav').read_bytes() + str(window['index']).encode())
        return {'path': str(file), 'sha256': digest(file)}

    def complete(self, request: dict) -> None:
        """Run the actual copy worker for donors and reseal each new current generation."""
        root = Path(request['output'])
        for index in range(len(request['revision']['renderWindows'])):
            phase = f'segment-picture-{index}'
            if phase in request['revision'].get('windowDonors', {}):
                with patch.object(worker, 'section_audio', side_effect=self.current_audio):
                    with patch('studio.native_segments.probe.execute_dependency_probe', side_effect=synthetic_dependency_probe):
                        worker.execute_segment(request, phase)
            else:
                self.f.write_phase(phase, root)
            self.seal(request, phase)

    def test_local_b_keeps_a_c_bytes_with_fresh_current_owner_and_audio(self) -> None:
        """A scoped HTML correction rerenders B while A/C retain their exact media digest."""
        request = self.child()
        Path(request['project'], 'index.html').write_text(HTML.format(middle='B repaired'))
        current = self.admit(request)
        self.assertEqual(current['revision']['repair']['affectedSections'], [1])
        self.assertEqual(current['revision']['repair']['recheckJoins'], [0, 1])
        self.assertEqual(set(current['revision']['windowDonors']), {'segment-picture-0', 'segment-picture-2'})
        with self.assertRaisesRegex(ValueError, 'current owner seal'):
            owners.current_window(current, 'segment-picture-0')
        self.complete(current)
        for index in (0, 2):
            phase = f'segment-picture-{index}'
            before, after = owners.current_window(self.f.request, phase), owners.current_window(current, phase)
            self.assertEqual(before['piece']['sha256'], after['piece']['sha256'])
            self.assertEqual(after['planIdentity'], current['revision']['identity'])
            self.assertNotEqual(before['audio']['sha256'], after['audio']['sha256'])
            self.assertEqual(after['piece']['origin'], 'reused')

    def test_audio_only_reuses_all_picture_and_refreshes_pcm(self) -> None:
        """Explicit unrendered Long audio may change without invalidating picture sections."""
        request = self.child()
        Path(request['project'], 'program.wav').write_bytes(b'TEST corrected program audio')
        current = self.admit(request)
        self.assertEqual(current['revision']['repair']['affectedSections'], [])
        self.assertEqual(len(current['revision']['windowDonors']), 3)
        self.complete(current)
        for index in range(3):
            phase = f'segment-picture-{index}'
            before, after = owners.current_window(self.f.request, phase), owners.current_window(current, phase)
            self.assertEqual(before['piece']['sha256'], after['piece']['sha256'])
            self.assertIn(b'corrected', Path(after['audio']['path']).read_bytes())

    def test_shared_style_and_timing_changes_broaden(self) -> None:
        """Untimed CSS or the absolute program clock cannot select local donors."""
        for name in ('style', 'clock', 'asset'):
            request = self.child(name)
            project = Path(request['project'])
            if name == 'style':
                (project / 'index.html').write_text(HTML.format(middle='B').replace('<body>', '<style>*{color:red}</style><body>'))
            elif name == 'asset':
                (project / 'assets/shared.png').write_bytes(b'TEST revised shared image')
            else:
                plan = json.loads((project / 'LONG-PROJECT.json').read_text())
                plan['canvas']['totalFrames'] += 1
                write_json(project / 'LONG-PROJECT.json', plan)
            current = self.admit(request)
            self.assertEqual(current['revision']['windowDonors'], {})

    def test_tool_drift_refuses_even_with_updated_current_pin(self) -> None:
        """New implementation bytes cannot inherit compatible section identities."""
        request = self.child()
        request['sectionImplementationPins'] = {**request['sectionImplementationPins'], str(self.f.node): 'f' * 64}
        request['pins'][str(self.f.node)] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'implementation or tool drift'):
            self.admit(request)

    def test_in_place_original_mutation_refuses(self) -> None:
        """A preserved path alone is not immutable source evidence."""
        request = self.child()
        (self.f.project / 'index.html').write_text(HTML.format(middle='mutated old snapshot'))
        with self.assertRaisesRegex(ValueError, 'changed input'):
            self.admit(request)

    def test_corrupt_donor_media_refuses(self) -> None:
        """A matching window identity cannot waive actual sealed media hashes."""
        request = self.child()
        row = owners.current_window(self.f.request, 'segment-picture-0')
        Path(row['piece']['path']).write_bytes(b'TEST corrupted donor')
        with self.assertRaises(ValueError):
            self.admit(request)

    def test_repair_dependency_or_generation_tamper_refuses_before_copy(self) -> None:
        """Recompute the relation instead of trusting a caller's compatible-window label."""
        request = self.admit(self.child())
        request['revision']['renderWindows'][0]['generation'] += 1
        with self.assertRaisesRegex(ValueError, 'plan or dependency closure changed'):
            compatible_donor(request, 'segment-picture-0')

    def test_second_repair_uses_current_parent_seals(self) -> None:
        """Repeated generations preserve unchanged work through freshly sealed evidence."""
        first = self.child()
        Path(first['project'], 'index.html').write_text(HTML.format(middle='B revision 2'))
        first = self.admit(first)
        self.complete(first)
        second = self.child('child-two', first)
        Path(second['project'], 'index.html').write_text(HTML.format(middle='B revision 3'))
        second = self.admit(second, first)
        self.assertEqual(second['revision']['renderWindows'][1]['generation'], 3)
        self.complete(second)
        self.assertEqual(owners.current_window(self.f.request, 'segment-picture-0')['piece']['sha256'],
                         owners.current_window(second, 'segment-picture-0')['piece']['sha256'])

    def test_old_audio_review_cannot_approve_reused_picture_with_new_pcm(self) -> None:
        """Retaining picture hashes never transfers a prior listening assessment."""
        _file, bundle = self.f.review_bundle()
        request = self.admit(self.child())
        self.complete(request)
        value = owners.current_window(request, 'segment-picture-0')
        with self.assertRaisesRegex(ValueError, 'current media'):
            validate_review(bundle['reviews'][0], value['window'], value['piece'], value['audio'])

    def test_exact_resume_preserves_repaired_plan_and_restores_new_parent_seals(self) -> None:
        """A completed A/C repair copy is itself durable; exact restart need not copy under another owner."""
        changed = self.child()
        Path(changed['project'], 'index.html').write_text(HTML.format(middle='B revised'))
        original = self.admit(changed)
        self.complete(original)
        current = {**changed, 'output': str(self.base / 'resumed'),
                   'revision': initial_long_plan(original['revision']['canvas'], 'f' * 64),
                   'sectionAttemptSequence': 2}
        resumed = prepare_section_recovery(current, Path(original['output']))
        resumed = owners.bind_window_recovery(resumed, [Path(original['output'])])
        self.assertEqual(resumed['revision']['identity'], original['revision']['identity'])
        self.assertEqual(resumed['sectionRepair'], original['sectionRepair'])
        Path(resumed['output']).mkdir()
        self.f.write_request(resumed)
        register_attempt(resumed)
        pipeline = SimpleNamespace(root=Path(resumed['output']), request=resumed, evidence={}, stages=[])
        for index in range(3):
            phase = f'segment-picture-{index}'
            self.assertTrue(owners.restore_window(pipeline, phase))
            self.assertEqual(owners.current_window(resumed, phase)['piece']['sha256'],
                             owners.current_window(original, phase)['piece']['sha256'])

    def test_exact_resume_rejects_changed_repaired_project(self) -> None:
        """Resume cannot hide new authored bytes behind the preserved repair manifest."""
        current = self.admit(self.child())
        changed = {**current, 'output': str(self.base / 'bad-resume'), 'pins': dict(current['pins'])}
        file = Path(current['project'], 'index.html')
        file.write_text(HTML.format(middle='unadmitted update'))
        changed['pins'][str(file)] = digest(file)
        with self.assertRaisesRegex(ValueError, 'current project or implementation'):
            prepare_section_recovery(changed, Path(current['output']))

    def test_retry_uses_durable_permission_and_a_new_owner_receipt(self) -> None:
        """Only a permitted transient retry gets the second canonical worker launch."""
        pipeline = SimpleNamespace(request=self.f.request)
        failure = RuntimeError('TEST transient owner failure')
        outcomes = iter([failure, None])
        with patch.object(owners, 'attempt_window', side_effect=lambda *_args: next(outcomes)) as run:
            with patch('studio.native_budget_sections.section_retry_allowed', return_value=True) as allowed:
                with patch('time.sleep') as sleep:
                    self.assertEqual(owners.supervise_window(pipeline, 'segment-picture-1', [0]),
                                     'segment-picture-1-retry-1')
        self.assertEqual([call.args[2] for call in run.call_args_list],
                         ['segment-picture-1', 'segment-picture-1-retry-1'])
        allowed.assert_called_once_with(self.f.request, 'segment-picture-1', failure)
        sleep.assert_called_once_with(1)

    def test_retry_refusal_preserves_original_failure_without_second_launch(self) -> None:
        """No retry limit or counter is invented locally when inherited admission refuses."""
        pipeline = SimpleNamespace(request=self.f.request)
        failure = RuntimeError('TEST deterministic owner failure')
        with patch.object(owners, 'attempt_window', return_value=failure) as run:
            with patch('studio.native_budget_sections.section_retry_allowed', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'deterministic owner failure'):
                    owners.supervise_window(pipeline, 'segment-picture-1', [0])
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
