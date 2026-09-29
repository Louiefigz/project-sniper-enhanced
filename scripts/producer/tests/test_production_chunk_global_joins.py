"""Independent join-input checks with real claims/seals and explicitly synthetic media."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from _production_chunk_fixture import ChunkFixture
from cut_preview_io import bound_json, write_new
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_segments.owners import restore_window
from studio.native_stage_evidence import read_stage
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.section_chunk_join_inputs import (
    KIND, chunk_global_join_inputs, validate_chunk_global_joins,
)
from studio.production.section_chunk_plan import (
    freeze_chunk_plan, read_chunk_plan, scope_manifest, scope_observations,
)
from studio.production.section_plan import pin_file, unique_pins
from studio.production.section_results import CHECKS, claim_directory, read_completed_result
from studio.production.section_join_barrier import matching_join
from studio.production.section_recovery import retain_section_reviews
from studio.production.sections import early_result, review_task


class ChunkGlobalJoinTests(unittest.TestCase):
    """A counted existing reviewer can judge only current, assigned full-project joins."""

    def setUp(self) -> None:
        """Register the actual last assignment's encoded reviewer and retain real media seals."""
        self.fixture = ChunkFixture(self)
        self.host = self.fixture.host
        host = self.host
        with attempt_reservation(host.request):
            register_attempt(host.request)
        row = host.context['assignments'][-1]
        record = host.budget.record()
        early_pin, early = early_result(host.request, row, record)
        author = record['production']['tasks'][row['authorTaskId']]['receipts'][0]
        plan = freeze_chunk_plan(host.request, row, host.budget.base / 'TEST-last-chunk-plan.json')
        binding = {**row['authorBinding'], 'role': 'encoded-review', 'authorTaskId': row['authorTaskId'],
                   'mediaManifest': None, 'chunkPlan': plan,
                   'inputs': unique_pins([*row['authorBinding']['inputs'], author, early_pin, plan])}
        spec = review_task(host.context, {**row, 'earlyTaskId': early.task_id}, binding)
        api.enqueue_tasks(host.budget.root, 'section-test', (spec,))
        claim = api.claim_task(host.budget.root, 'section-test', spec.task_id, host.handle('director'))
        self.ref = ClaimRef(spec.task_id, claim['epoch'], claim['token'])
        api.attach_task(host.budget.root, 'section-test', self.ref, host.handle('TEST-last-reviewer'))
        self.task = host.budget.record()['production']['tasks'][spec.task_id]
        claim_directory(self.task).mkdir(parents=True)
        for index in range(3):
            host.seal(index)
        self.request_pin = pin_file(Path(host.request['output']) / 'export-request.json')

    def document(self) -> dict:
        """Describe synthetic judgments over the helper's actual current evidence inventory."""
        _request, scopes = chunk_global_join_inputs(self.task['sectionBinding'], self.request_pin)
        return {'schemaVersion': 1, 'kind': KIND, 'chunkPlan': self.task['sectionBinding']['chunkPlan'],
                'request': self.request_pin, 'judgments': [
                    {'id': scope['id'], 'checks': dict.fromkeys(CHECKS, True),
                     'assessments': dict.fromkeys(CHECKS, 'TEST fictional judgment; no playback approval'),
                     'observations': scope['observations']} for scope in scopes]}

    def receipt(self, document: dict) -> dict:
        """Create one canonical receipt in the existing reviewer's exact claim directory."""
        file = claim_directory(self.task) / 'global-joins.json'
        write_new(file, document)
        return pin_file(file)

    def complete_last(self) -> dict:
        """Complete one real counted task with fictional chunk and explicit global-join judgments."""
        binding = self.task['sectionBinding']
        scope = read_chunk_plan(binding)[0]['scopes'][0]
        directory = claim_directory(self.task)
        (directory / 'chunks').mkdir()
        media = scope_manifest(binding, scope['id'], directory / 'chunks' / 'media.json')
        value = {'schemaVersion': 1, 'kind': 'native-long-section-chunk-result',
                 'taskId': self.ref.task_id, 'epoch': self.ref.epoch, 'token': self.ref.token,
                 'chunkPlan': binding['chunkPlan'], 'scopeId': scope['id'], 'mediaManifest': media,
                 'review': {'status': 'pass', 'checks': dict.fromkeys(CHECKS, True),
                            'assessments': dict.fromkeys(CHECKS, 'TEST fictional playback'),
                            'observations': scope_observations(binding, scope['id'], media)}}
        file = directory / 'chunks' / f"{scope['id']}.json"
        write_new(file, value)
        progress = pin_file(file)
        api.record_section_review_progress(self.host.budget.root, 'section-test', self.ref, progress)
        joins = self.receipt(self.document())
        final = {'schemaVersion': 1, 'kind': 'native-long-section-result', 'taskId': self.ref.task_id,
                 'epoch': self.ref.epoch, 'token': self.ref.token, 'binding': binding,
                 'artifacts': [joins], 'review': {'status': 'pass', 'progress': [progress], 'globalJoins': joins}}
        file = directory / 'result.json'
        write_new(file, final)
        api.complete_task(self.host.budget.root, 'section-test', self.ref, TaskResult((pin_file(file),)))
        return final

    def register_resume(self, changed_preview: bool = False) -> dict:
        """Publish a newer registered exact-plan attempt without changing any original evidence."""
        request = copy.deepcopy(self.host.request)
        output = self.host.budget.base / 'TEST-exact-resume'
        output.mkdir()
        request.update(output=str(output), sectionAttemptSequence=2)
        request['revision']['windowDonors'] = {f'segment-picture-{index}':
            str(self.host.fixture.root / f'segment-picture-{index}-stage.json') for index in range(3)}
        for phase, name in request['revision']['windowDonors'].items():
            _record, pins = read_stage(Path(name), bound_json(Path(name))['inputs'], phase)
            request['pins'].update(pins)
        if not changed_preview:
            request = retain_section_reviews(request, self.host.request)
        write_new(output / 'export-request.json', request)
        with attempt_reservation(request):
            register_attempt(request)
        pipeline = NativeShortPipeline(request, {})
        for phase in request['revision']['windowDonors']:
            self.assertTrue(restore_window(pipeline, phase))
        if changed_preview:
            self.changed_preview(request)
        return request

    def changed_preview(self, request: dict) -> None:
        """Create another genuine preview receipt over intentionally different synthetic media bytes."""
        output = Path(request['output'])
        preview = copy.deepcopy(self.host.preview)
        for index, clip in enumerate(preview['clips']):
            file = output / f'TEST-changed-preview-{index}.mp4'
            file.write_text(f'TEST different preview bytes {index}')
            clip.update(pin_file(file))
        file = output / 'motion-previews.json'
        write_new(file, preview)
        pin = pin_file(output / 'export-request.json')
        owner = self.host.fixture.owner_record(request, {pin['path']: pin['sha256']},
                                               preview['status'], str(file))
        write_new(output / 'preview.render.json', {**owner, 'completedAt': 'TEST completed'})

    def test_current_two_stage_join_reads_without_new_task_or_charge(self) -> None:
        """Both continuous preview and encoded boundary evidence use the same counted reviewer."""
        before = self.host.budget.record()
        scopes = validate_chunk_global_joins(before, self.task, self.receipt(self.document()))
        self.assertEqual([row['id'] for row in scopes], ['early-join:first:last', 'encoded-join:first:last'])
        self.assertEqual({row['kind'] for row in scopes[0]['observations']}, {'moving-preview', 'audio-listening'})
        self.assertEqual({row['kind'] for row in scopes[1]['observations']}, {'encoded-playback', 'audio-listening'})
        self.assertEqual(before, self.host.budget.record())
        self.assertEqual(before['clips']['A']['counters']['review'], 4)

    def test_missing_stage_or_changed_observation_refuses(self) -> None:
        """A global pass cannot omit encoded joins or substitute a declared frame range."""
        document = self.document()
        document['judgments'].pop()
        with self.assertRaisesRegex(ValueError, 'omits required'):
            validate_chunk_global_joins(self.host.budget.record(), self.task, self.receipt(document))

    def test_involved_author_cannot_be_join_reviewer(self) -> None:
        """Independence covers the neighboring author as well as the reviewer's own section."""
        record = self.host.budget.record()
        first = self.host.context['assignments'][0]['authorTaskId']
        task = copy.deepcopy(self.task)
        task['handle'] = record['production']['tasks'][first]['handle']
        with self.assertRaisesRegex(ValueError, 'involved author'):
            validate_chunk_global_joins(record, task, self.receipt(self.document()))

    def test_unassigned_reviewer_and_foreign_claim_path_refuse(self) -> None:
        """A valid join document does not transfer to another section or output directory."""
        pin = self.receipt(self.document())
        record = self.host.budget.record()
        with self.assertRaisesRegex(ValueError, 'unassigned'):
            validate_chunk_global_joins(record, self.fixture.task(), pin)
        file = self.host.budget.base / 'global-joins.json'
        file.write_bytes(Path(pin['path']).read_bytes())
        with self.assertRaisesRegex(ValueError, 'current reviewer claim'):
            validate_chunk_global_joins(record, self.task, pin_file(file))

    def test_changed_request_digest_or_sealed_media_refuses(self) -> None:
        """Registered paths cannot make changed request bytes or old encoded evidence current."""
        bad = {**self.request_pin, 'sha256': 'f' * 64}
        with self.assertRaises(ValueError):
            chunk_global_join_inputs(self.task['sectionBinding'], bad)
        document = self.document()
        pin = self.receipt(document)
        Path(document['judgments'][1]['observations'][0]['path']).write_text('TEST altered picture')
        with self.assertRaises((ValueError, RuntimeError)):
            validate_chunk_global_joins(self.host.budget.record(), self.task, pin)

    def test_superseded_neighbor_author_invalidates_join(self) -> None:
        """A formerly current neighboring judgment is reread against registered task state."""
        pin = self.receipt(self.document())
        first = self.host.context['assignments'][0]['authorTaskId']
        api.supersede_task(self.host.budget.root, 'section-test', first, 'TEST changed generation')
        with self.assertRaisesRegex(ValueError, 'not current'):
            validate_chunk_global_joins(self.host.budget.record(), self.task, pin)

    def test_completed_join_remains_readable_after_registered_exact_resume(self) -> None:
        """New attempt paths do not erase completed immutable evidence or spend another review."""
        final = self.complete_last()
        before = self.host.budget.record()['clips']['A']['counters']['review']
        self.register_resume()
        actual = read_completed_result(self.host.budget.record(), self.ref.task_id,
                                       self.task['sectionBinding'])
        self.assertEqual(actual, final)
        self.assertEqual(self.host.budget.record()['clips']['A']['counters']['review'], before)

    def test_running_reviewer_cannot_publish_old_attempt_after_resume(self) -> None:
        """Retained completed evidence does not give a live callback authority to approve old work."""
        pin = self.receipt(self.document())
        self.register_resume()
        with self.assertRaisesRegex(ValueError, 'superseded'):
            validate_chunk_global_joins(self.host.budget.record(), self.task, pin)
        self.assertEqual(self.host.budget.record()['production']['tasks'][self.ref.task_id]['state'], 'running')

    def test_barrier_accepts_same_current_join_bytes_after_exact_resume(self) -> None:
        """Completed old inputs are compared against real donor seals and retained preview authority."""
        self.complete_last()
        current = self.register_resume()
        task = self.host.budget.record()['production']['tasks'][self.ref.task_id]
        pair = tuple(self.host.context['assignments'])
        for stage in ('early', 'encoded'):
            with self.subTest(stage=stage):
                self.assertIsNotNone(matching_join(current, task, (pair, stage)))

    def test_barrier_rejects_changed_current_continuous_join_preview(self) -> None:
        """A current independently sealed new preview cannot borrow an old judgment for other bytes."""
        self.complete_last()
        current = self.register_resume(changed_preview=True)
        task = self.host.budget.record()['production']['tasks'][self.ref.task_id]
        pair = tuple(self.host.context['assignments'])
        with self.assertRaisesRegex(ValueError, 'preview differs'):
            matching_join(current, task, (pair, 'early'))


if __name__ == '__main__':
    unittest.main()
