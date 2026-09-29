"""Incremental reviewer callbacks exercise real claims/caps/seals; media and judgments are synthetic."""
from __future__ import annotations

import json
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from _production_chunk_fixture import ChunkFixture
from cut_preview_io import write_new
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.section_chunk_results import read_chunk_completion
from studio.production.section_plan import pin_file
from studio.production.section_results import read_completed_result
from studio.production.tasks import StaleClaim, TaskConflict, TaskRefused


class ChunkProgressTests(unittest.TestCase):
    """A single assigned reviewer records partial work without completing or resetting its grant."""

    def setUp(self) -> None:
        """Keep synthetic files and real production authority isolated from operator projects."""
        self.fixture = ChunkFixture(self)
        self.host = self.fixture.host

    def test_first_chunk_records_while_later_chunk_is_unfinished(self) -> None:
        """Partial QC uses one charge and cannot become final until chunks and edge are current."""
        self.host.seal(0)
        pin = self.fixture.progress(0)
        self.assertTrue(self.fixture.record(pin)['committed'])
        self.assertFalse(self.fixture.record(pin)['committed'])
        self.assertEqual(self.fixture.task()['state'], 'running')
        self.assertEqual(self.fixture.task()['receipts'], [])
        self.assertFalse((self.host.fixture.root / 'segment-picture-1-stage.json').exists())
        self.assertEqual(self.host.budget.record()['clips']['A']['counters']['review'], 3)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            read_chunk_completion(self.fixture.task(), {'status': 'pass', 'progress': [pin], 'globalJoins': None})
        self.host.seal(1)
        self.fixture.record(self.fixture.progress(1))
        self.fixture.record(self.fixture.progress(2))
        task = self.fixture.task()
        pins = [task['sectionProgress'][row['id']] for row in self.fixture.scopes()]
        self.assertEqual(len(read_chunk_completion(task, {'status': 'pass', 'progress': pins, 'globalJoins': None})), 3)
        self.assertEqual(self.host.budget.record()['clips']['A']['counters']['review'], 3)

    def test_stale_claim_and_conflicting_scope_do_not_publish(self) -> None:
        """Epoch fencing and immutable evidence survive replay and changed review prose."""
        self.host.seal(0)
        pin = self.fixture.progress(0)
        ref = self.fixture.ref
        with self.assertRaises(StaleClaim):
            api.record_section_review_progress(self.host.budget.root, 'section-test',
                ClaimRef(ref.task_id, ref.epoch + 1, ref.token), pin)
        self.fixture.record(pin)
        value = json.loads(Path(pin['path']).read_text())
        value['review']['assessments']['audio'] = 'TEST changed judgment'
        Path(pin['path']).unlink()
        write_new(Path(pin['path']), value)
        with self.assertRaises(TaskConflict):
            self.fixture.record(pin_file(Path(pin['path'])))

    def test_superseded_author_invalidates_progress(self) -> None:
        """Repair cannot inherit an old review by merely retaining matching media paths."""
        self.host.seal(0)
        pin = self.fixture.progress(0)
        self.fixture.record(pin)
        author = self.fixture.spec.section_binding['authorTaskId']
        api.supersede_task(self.host.budget.root, 'section-test', author, 'TEST repair changes author generation')
        with self.assertRaisesRegex(ValueError, 'not current'):
            self.fixture.record(pin)

    def test_expiry_after_real_proof_hashes_does_not_commit(self) -> None:
        """The unchanged original grant is checked after sealed media and author bytes are rehashed."""
        from studio.production.section_chunk_progress import read_progress
        self.host.seal(0)
        pin = self.fixture.progress(0)
        def expensive(task: dict, receipt: dict) -> dict:
            """Advance only after the actual proof reader succeeds."""
            value = read_progress(task, receipt)
            self.host.budget.elapsed = 9001
            return value
        with patch('studio.production.section_chunk_progress.read_progress', side_effect=expensive):
            with self.assertRaisesRegex(TaskRefused, 'deadline expired'):
                self.fixture.record(pin)
        self.assertNotIn('sectionProgress', self.fixture.task())

    def test_corrupt_sealed_media_invalidates_previously_recorded_progress(self) -> None:
        """Recording a pass does not turn future evidence reads into cached approval."""
        self.host.seal(0)
        pin = self.fixture.progress(0)
        self.fixture.record(pin)
        value = json.loads(Path(pin['path']).read_text())
        picture = value['review']['observations'][0]['path']
        Path(picture).write_text('TEST corrupt encoded media')
        with self.assertRaises((ValueError, RuntimeError)):
            self.fixture.record(pin)

    def test_final_callback_requires_all_current_scopes_then_completes_once(self) -> None:
        """Only the ordinary final callback ends the task and releases its already charged slot."""
        for index in (0, 1):
            self.host.seal(index)
        for index in (0, 1, 2):
            self.fixture.record(self.fixture.progress(index))
        pin = self.fixture.final()
        api.complete_task(self.host.budget.root, 'section-test', self.fixture.ref, TaskResult((pin,)))
        self.assertEqual(self.fixture.task()['state'], 'completed')
        document = read_completed_result(self.host.budget.record(), self.fixture.ref.task_id,
                                         self.fixture.spec.section_binding)
        self.assertEqual(len(document['review']['progress']), 3)
        replay = api.complete_task(self.host.budget.root, 'section-test', self.fixture.ref, TaskResult((pin,)))
        self.assertFalse(replay['committed'])
        self.assertEqual(self.host.budget.record()['clips']['A']['counters']['review'], 3)

    def test_final_callback_cannot_turn_partial_progress_into_completion(self) -> None:
        """A passing top-level label cannot omit any frozen chunk or internal edge."""
        self.host.seal(0)
        self.fixture.record(self.fixture.progress(0))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            api.complete_task(self.host.budget.root, 'section-test', self.fixture.ref,
                              TaskResult((self.fixture.final(),)))
        self.assertEqual(self.fixture.task()['state'], 'running')

    def test_waiting_reviewer_keeps_slot_and_cannot_release_attached_claim(self) -> None:
        """The coordinator must reserve author capacity; progress never evades the shared slot ledger."""
        from studio.production.claims import active_ai
        before = self.host.budget.record()
        active = active_ai(before)
        self.host.seal(0)
        self.fixture.record(self.fixture.progress(0))
        self.assertEqual(active_ai(self.host.budget.record()), active)
        with self.assertRaises(TaskRefused):
            api.release_claim(self.host.budget.root, 'section-test', self.fixture.ref)
        # A spare existing slot remains usable by an unfinished registered author.
        pending = next(row for row in before['production']['tasks'].values()
                       if row['kind'] == 'author' and row['state'] == 'ready')
        self.assertLess(active, before['production']['ai']['slots'])
        claimed = api.claim_task(self.host.budget.root, 'section-test', pending['id'],
                                 self.host.handle('director'))
        self.assertEqual(claimed['taskId'], pending['id'])

    def test_changed_generation_and_author_host_cannot_record_progress(self) -> None:
        """Old frozen chunks cannot approve a new generation or a self-reviewing host."""
        from studio.production.section_chunk_progress import record_progress
        from studio.production.section_chunk_results import read_progress
        self.host.seal(0)
        pin = self.fixture.progress(0)
        task = copy.deepcopy(self.fixture.task())
        task['sectionBinding']['generation'] += 1
        with self.assertRaisesRegex(ValueError, 'generation differs'):
            read_progress(task, pin)
        record = self.host.budget.record()
        task = record['production']['tasks'][self.fixture.ref.task_id]
        author = record['production']['tasks'][task['sectionBinding']['authorTaskId']]
        task['handle'] = author['handle']
        with self.assertRaisesRegex(ValueError, 'reviewer is the author'):
            record_progress(record, self.fixture.ref, pin)

    def test_final_clock_is_rechecked_after_all_proofs(self) -> None:
        """A complete inventory still cannot settle after its original grant expires during hashing."""
        from studio.production.section_chunk_results import validate_chunk_review
        for index in (0, 1):
            self.host.seal(index)
        for index in (0, 1, 2):
            self.fixture.record(self.fixture.progress(index))
        pin = self.fixture.final()
        def expensive(record: dict, task: dict, document: dict) -> None:
            """Advance only after all real interior and applicable global join proof checks."""
            validate_chunk_review(record, task, document)
            self.host.budget.elapsed = 9001
        with patch('studio.production.section_chunk_results.validate_chunk_review', side_effect=expensive):
            with self.assertRaisesRegex(TaskRefused, 'deadline expired'):
                api.complete_task(self.host.budget.root, 'section-test', self.fixture.ref, TaskResult((pin,)))
        self.assertEqual(self.fixture.task()['state'], 'running')
        self.assertEqual(self.fixture.task()['receipts'], [])


if __name__ == '__main__':
    unittest.main()
