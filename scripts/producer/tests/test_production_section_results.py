"""Independent byte/claim/identity checks; synthetic media is never editorial evidence."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cross_runtime_canonical_json import canonical_compact_json
from studio.production.callbacks import TaskResult, complete
from studio.production.claims import ClaimRef
from studio.production.section_results import (
    CHECKS, claim_directory, read_completed_result, validate_binding, validate_result,
)


def pin(file: Path) -> dict:
    """Bind exact fixture bytes using the public receipt shape."""
    raw = file.read_bytes()
    return {'path': str(file), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


class SectionResultTests(unittest.TestCase):
    """Exercise actual result readers and completion callbacks with isolated registered tasks."""

    def setUp(self) -> None:
        """Make a completed author and frozen synthetic shared plan/preview inputs."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.shared = self.file('shared.json', b'{"TEST":"shared creative plan"}')
        self.picture = self.file('TEST-preview.mp4', b'TEST synthetic nondecodable picture')
        self.audio = self.file('TEST-audio.wav', b'TEST synthetic nondecodable audio')
        self.record = {'batchId': 'run', 'production': {'tasks': {}}, 'clips': {'long': {'approvals': []}}}
        self.enterContext(patch('studio.production.section_media.read_media_manifest',
                                side_effect=self.media_observations))
        self.author = self.task('author-1', 'author')
        self.author_pin = self.result(self.author)
        self.finish(self.author, self.author_pin)

    def media_observations(self, binding: dict) -> list[dict]:
        """Isolate result ownership tests; manifest seal validation has separate behavioral tests."""
        return [{'kind': kind, 'path': media['path'], 'sha256': media['sha256'], 'frameRange': [0, 75]}
                for kind, media in (('encoded-playback', self.picture), ('audio-listening', self.audio))]

    def file(self, name: str, raw: bytes) -> dict:
        """Write an inert fixture outside task-owned outputs and return its digest."""
        file = self.root / name
        file.write_bytes(raw)
        return pin(file)

    def task(self, task_id: str, role: str) -> dict:
        """Declare a registered claimed host task, without pretending the handle is authenticated."""
        author = role == 'author'
        binding = {'role': role, 'sectionId': 'section-A', 'generation': 1,
                   'sharedPlanSha256': self.shared['sha256'], 'inputIdentity': 'a' * 64,
                   'frameRange': [0, 75], 'outputRoot': str(self.root / 'owned'),
                   'mediaManifest': self.shared if role == 'encoded-review' else None,
                   'authorTaskId': None if author else self.author['id'],
                   'inputs': [self.shared] if author else
                   [self.shared, self.author_pin, self.picture, self.audio]}
        row = {'id': task_id, 'runId': 'run', 'clipId': 'long', 'kind': 'author' if author else 'review',
               'sectionBinding': binding, 'claim': {'epoch': 1, 'token': 'f' * 32, 'approval': None},
               'handle': {'type': 'host', 'host': 'codex', 'thread': task_id, 'turn': 'turn-1'},
               'deadlineElapsed': 10.0, 'owners': [],
               'state': 'running', 'supersededBy': None, 'unresolved': False, 'approvalStale': False, 'revoked': False,
               'cancelRequested': False, 'endConfirmed': False, 'receipts': [], 'reason': None,
               'prerequisites': [] if author else [self.author['id']], 'parent': None}
        self.record['production']['tasks'][task_id] = row
        return row

    def result(self, task: dict, change: dict | None = None) -> dict:
        """Publish exact canonical synthetic output in its derived claim-owned directory."""
        directory = claim_directory(task)
        directory.mkdir(parents=True, exist_ok=True)
        artifacts, review = [], None
        if task['sectionBinding']['role'] == 'author':
            artifact = directory / 'authored.html'
            artifact.write_bytes(b'TEST authored section')
            artifacts = [pin(artifact)]
        else:
            picture_kind = 'moving-preview' if task['sectionBinding']['role'] == 'early-review' else 'encoded-playback'
            observations = [{'kind': kind, 'path': media['path'], 'sha256': media['sha256'], 'frameRange': [0, 75]}
                            for kind, media in ((picture_kind, self.picture), ('audio-listening', self.audio))]
            review = {'status': 'pass', 'checks': dict.fromkeys(CHECKS, True),
                      'assessments': dict.fromkeys(CHECKS, 'TEST declaration, no actual review'),
                      'observations': observations}
        document = {'schemaVersion': 1, 'kind': 'native-long-section-result', 'taskId': task['id'],
                    'epoch': task['claim']['epoch'], 'token': task['claim']['token'],
                    'binding': task['sectionBinding'], 'artifacts': artifacts, 'review': review}
        document.update(change or {})
        file = directory / 'result.json'
        file.write_bytes((canonical_compact_json(document) + '\n').encode())
        return pin(file)

    def finish(self, task: dict, receipt: dict) -> None:
        """Use the real fenced callback after independent artifact validation."""
        ref = ClaimRef(task['id'], task['claim']['epoch'], task['claim']['token'])
        validate_result(self.record, ref, receipt)
        complete(self.record, ref, TaskResult((receipt,)), 1.0)

    def test_author_and_both_review_roles_revalidate_completed_bytes(self) -> None:
        """Current distinct registered threads complete and the barrier reads their exact inputs."""
        for role in ('early-review', 'encoded-review'):
            task = self.task(role, role)
            self.finish(task, self.result(task))
            value = read_completed_result(self.record, task['id'], task['sectionBinding'])
            self.assertEqual(value['review']['status'], 'pass')

    def test_changed_authored_bytes_block_even_previously_completed_review(self) -> None:
        """Result completion cannot make later corruption current by historical status alone."""
        task = self.task('review', 'encoded-review')
        self.finish(task, self.result(task))
        (claim_directory(self.author) / 'authored.html').write_bytes(b'TEST altered section')
        with self.assertRaisesRegex(ValueError, 'artifact bytes changed'):
            read_completed_result(self.record, task['id'], task['sectionBinding'])

    def test_same_host_thread_with_distinct_turn_and_task_cannot_self_approve(self) -> None:
        """A new task id or turn is not independent reviewer identity."""
        task = self.task('review', 'early-review')
        task['handle'] = {**self.author['handle'], 'turn': 'different-turn'}
        with self.assertRaisesRegex(ValueError, 'author host thread'):
            self.finish(task, self.result(task))

    def test_generation_mismatch_and_stale_author_block_review(self) -> None:
        """Matching bytes cannot transfer an author judgment to a new local generation."""
        task = self.task('review', 'encoded-review')
        task['sectionBinding']['generation'] = 2
        with self.assertRaisesRegex(ValueError, 'stale reviewed author'):
            self.finish(task, self.result(task))
        task['sectionBinding']['generation'] = 1
        self.author.update(state='superseded', revoked=True)
        with self.assertRaisesRegex(ValueError, 'not current'):
            self.finish(task, self.result(task))

    def test_foreign_owned_artifact_and_duplicate_path_refused(self) -> None:
        """One claim cannot publish another task's output or list it twice."""
        task = self.task('author-2', 'author')
        foreign = pin(claim_directory(self.author) / 'authored.html')
        for artifacts, message in (([foreign], 'escapes'), ([foreign, foreign], 'duplicate')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.finish(task, self.result(task, {'artifacts': artifacts}))

    def test_result_outside_claim_directory_and_stale_epoch_refused(self) -> None:
        """Both on-disk namespace and recorded claim identify the completed execution."""
        task = self.task('review', 'encoded-review')
        receipt = self.result(task)
        outside = self.root / 'outside.json'
        outside.write_bytes(Path(receipt['path']).read_bytes())
        with self.assertRaisesRegex(ValueError, 'outside its claim'):
            self.finish(task, pin(outside))
        with self.assertRaisesRegex(ValueError, 'stale completion claim'):
            validate_result(self.record, ClaimRef(task['id'], 2, 'f' * 32), receipt)

    def test_linked_input_and_linked_owned_output_refused(self) -> None:
        """Canonical no-follow readers reject links despite matching bytes."""
        task = self.task('author-2', 'author')
        receipt = self.result(task)
        authored = claim_directory(task) / 'authored.html'
        authored.unlink()
        authored.symlink_to(claim_directory(self.author) / 'authored.html')
        with self.assertRaises((ValueError, RuntimeError)):
            self.finish(task, receipt)

    def test_observations_bind_full_range_and_current_media(self) -> None:
        """Partial playback and unpinned evidence cannot satisfy the complete section."""
        task = self.task('review', 'encoded-review')
        receipt = self.result(task)
        document = read_completed_result(self.record, self.author['id'], self.author['sectionBinding'])
        self.assertIsNone(document['review'])
        review = json.loads(Path(receipt['path']).read_bytes())['review']
        review['observations'][0]['frameRange'] = [0, 74]
        with self.assertRaisesRegex(ValueError, 'complete pinned current media'):
            self.finish(task, self.result(task, {'review': review}))

    def test_closed_binding_refuses_bool_generation_and_extra_keys(self) -> None:
        """Schema readers reject coercion and unknown authority fields without filesystem writes."""
        binding = self.author['sectionBinding']
        for change in ({'generation': True}, {'arbitrary': 'field'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_binding({**binding, **change})

    def test_assembly_expected_binding_and_missing_author_pin_refused(self) -> None:
        """Current generation comes from assembly authority, not the result's own declaration."""
        expected = {**self.author['sectionBinding'], 'inputIdentity': 'b' * 64}
        with self.assertRaisesRegex(ValueError, 'differs from current assembly'):
            read_completed_result(self.record, self.author['id'], expected)
        task = self.task('review', 'encoded-review')
        task['sectionBinding']['inputs'].remove(self.author_pin)
        with self.assertRaisesRegex(ValueError, 'pin its author result'):
            self.finish(task, self.result(task))

    def test_failed_checks_and_missing_assessments_cannot_complete(self) -> None:
        """Explicit pass status does not erase a failed or unexplained judgment."""
        task = self.task('review', 'early-review')
        receipt = self.result(task)
        review = json.loads(Path(receipt['path']).read_bytes())['review']
        review['checks']['audio'] = False
        with self.assertRaisesRegex(ValueError, 'missing or failed'):
            self.finish(task, self.result(task, {'review': review}))
        review['checks']['audio'] = True
        review['assessments']['motion'] = ' '
        with self.assertRaisesRegex(ValueError, 'assessments'):
            self.finish(task, self.result(task, {'review': review}))

    def test_unknown_or_process_execution_cannot_be_a_review_identity(self) -> None:
        """A declared process or unknown host cannot substitute for a registered reviewer turn."""
        task = self.task('review', 'encoded-review')
        receipt = self.result(task)
        for handle in (None, {'type': 'process', 'pid': 1, 'pgid': 1, 'started': 'TEST'}):
            task['handle'] = handle
            with self.subTest(handle=handle), self.assertRaisesRegex(ValueError, 'exact host turn'):
                self.finish(task, receipt)

    def test_canonical_result_refuses_duplicate_key_and_supports_unicode_notes(self) -> None:
        """Exact serialization prevents ambiguous keys without prohibiting reviewer punctuation."""
        task = self.task('review', 'encoded-review')
        receipt = self.result(task)
        document = json.loads(Path(receipt['path']).read_bytes())
        document['review']['assessments']['motion'] = 'TEST readable café — no actual playback'
        receipt = self.result(task, {'review': document['review']})
        ref = ClaimRef(task['id'], 1, 'f' * 32)
        validate_result(self.record, ref, receipt)
        file = Path(receipt['path'])
        file.write_bytes(file.read_bytes().replace(b'{', b'{"taskId":"duplicate",', 1))
        with self.assertRaisesRegex(ValueError, 'canonical JSON'):
            validate_result(self.record, ref, pin(file))

    def test_duplicate_input_path_and_unpinned_shared_plan_refused(self) -> None:
        """A schema-valid task has one exact meaning for each input path and its shared plan."""
        binding = self.author['sectionBinding']
        for change in ({'inputs': [self.shared, self.shared]}, {'sharedPlanSha256': 'e' * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_binding({**binding, **change})

    def test_early_muxed_preview_can_record_picture_and_audio_for_contained_sample(self) -> None:
        """Representative muxed previews do not require an expensive full logical render."""
        task = self.task('early', 'early-review')
        receipt = self.result(task)
        review = json.loads(Path(receipt['path']).read_bytes())['review']
        for row in review['observations']:
            row.update(path=self.picture['path'], sha256=self.picture['sha256'], frameRange=[5, 20])
        self.finish(task, self.result(task, {'review': review}))
        read_completed_result(self.record, task['id'], task['sectionBinding'])

    def test_early_preview_outside_assignment_and_duplicate_observation_refused(self) -> None:
        """A contained sample still must bind its section and cannot duplicate one observation."""
        task = self.task('early', 'early-review')
        receipt = self.result(task)
        review = json.loads(Path(receipt['path']).read_bytes())['review']
        review['observations'][0]['frameRange'] = [0, 76]
        with self.assertRaisesRegex(ValueError, 'contained media'):
            self.finish(task, self.result(task, {'review': review}))
        review['observations'][0]['frameRange'] = [0, 75]
        review['observations'].append(review['observations'][0])
        with self.assertRaisesRegex(ValueError, 'kinds or paths'):
            self.finish(task, self.result(task, {'review': review}))

    def test_fenced_completion_settles_without_reviving_publication(self) -> None:
        """Late owned results free an execution slot while retaining its fenced terminal state."""
        for state in ('superseded', 'abandoned'):
            task = self.task(f'late-{state}', 'author')
            receipt = self.result(task)
            task.update(state=state, unresolved=True, revoked=state == 'superseded',
                        supersededBy='new-generation' if state == 'superseded' else None)
            ref = ClaimRef(task['id'], 1, 'f' * 32)
            outcome = complete(self.record, ref, TaskResult((receipt,)), 2.0)
            self.assertFalse(outcome.event['publishable'])
            self.assertEqual(task['state'], state)
            self.assertTrue(task['endConfirmed'])
            self.assertFalse(task['unresolved'])
            self.assertFalse(complete(self.record, ref, TaskResult((receipt,)), 3.0).changed)
            with self.assertRaisesRegex(ValueError, 'not current'):
                read_completed_result(self.record, task['id'], task['sectionBinding'])

    def test_fenced_settlement_still_rejects_changed_owned_output(self) -> None:
        """Historical settlement does not excuse invalid ownership or altered reported bytes."""
        task = self.task('late', 'author')
        receipt = self.result(task)
        task.update(state='superseded', unresolved=True, revoked=True, supersededBy='replacement')
        (claim_directory(task) / 'authored.html').write_bytes(b'TEST changed after result')
        with self.assertRaisesRegex(ValueError, 'artifact bytes changed'):
            complete(self.record, ClaimRef(task['id'], 1, 'f' * 32), TaskResult((receipt,)), 2.0)
        self.assertTrue(task['unresolved'])
        self.assertFalse(task['endConfirmed'])


if __name__ == '__main__':
    unittest.main()
