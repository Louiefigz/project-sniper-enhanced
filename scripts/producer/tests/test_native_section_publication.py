"""The final publication fence holds real batch authority before export history."""
from __future__ import annotations

import threading
import unittest
import json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

from _native_section_budget_fixture import SectionBudgetFixture
from studio.native_budget_store import locked_batch
from studio.production.section_publication import publish_delivery, section_publication


class SectionPublicationTests(unittest.TestCase):
    """Use a private real store and a competing writer; no media or host processes."""

    def setUp(self) -> None:
        """Complete fixture authorization and bind task/export identities to the same store."""
        self.fixture = SectionBudgetFixture(self)
        record = self.fixture.record()
        record['production']['authorization'].update(setup='complete', setupElapsed=0)
        self.fixture.raw(record)
        self.request = dict(self.fixture.request)
        self.request['sectionProduction'] = {key: self.request['productionBudget'][key]
                                            for key in ('authority', 'batchId', 'clipId')}
        self.events = []

    @contextmanager
    def history(self, _request: dict):
        """Observe the inner history scope without touching account export history."""
        self.events.append('history-enter')
        yield
        self.events.append('history-exit')

    def test_competing_authority_change_waits_until_promotion_finishes(self) -> None:
        """A superseding authority writer cannot fit between validation and publication."""
        attempted, acquired = threading.Event(), threading.Event()
        failures = []
        def handoff() -> None:
            """Represent an independent authority writer using the real same batch lock."""
            attempted.set()
            try:
                with locked_batch(self.fixture.root, 'section-test') as session:
                    acquired.set()
                    record = session.read()
                    record['clips']['A']['state'] = 'handed-off'
                    session.commit(record, {'event': 'clip-handed-off'})
            except Exception as error:
                failures.append(error)
        with patch('studio.production.section_publication.attempt_reservation', self.history):
            with section_publication(self.request) as record:
                self.assertEqual(record['clips']['A']['state'], 'active')
                worker = threading.Thread(target=handoff)
                worker.start()
                self.assertTrue(attempted.wait(1))
                self.assertFalse(acquired.wait(.05))
                self.events.append('published')
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(acquired.is_set())
        self.assertEqual(self.events, ['history-enter', 'published', 'history-exit'])
        with self.assertRaisesRegex(ValueError, 'handed off'):
            with section_publication(self.request):
                self.fail('Stale authority reached publication')

    def test_mismatched_task_authority_never_enters_history(self) -> None:
        """A request cannot check one batch while promoting another batch's section result."""
        self.request['sectionProduction']['clipId'] = 'B'
        with patch('studio.production.section_publication.attempt_reservation') as history:
            with self.assertRaisesRegex(ValueError, 'authority differ'):
                with section_publication(self.request):
                    self.fail('Mismatched publication was admitted')
        history.assert_not_called()

    def test_expired_original_clock_never_enters_history(self) -> None:
        """Completed media cannot quietly extend the output's admitted delivery deadline."""
        self.fixture.elapsed = 10801
        with patch('studio.production.section_publication.attempt_reservation') as history:
            with self.assertRaisesRegex(ValueError, 'deadline has passed'):
                with section_publication(self.request):
                    self.fail('Expired publication was admitted')
        history.assert_not_called()

    def test_expiry_during_snapshot_hashing_cannot_publish_success(self) -> None:
        """Both locks exclude mutation, but neither lock stops the original delivery clock."""
        root = Path(self.request['output'])
        root.mkdir()
        self.request['revision']['mode'] = 'initial-long'
        (root / 'revision-picture.json').write_text('{"sectionSnapshot":{"TEST":"snapshot"}}')
        result = {'status': 'native-long-checked-for-review'}
        def snapshot(_request: dict, _record: dict) -> dict:
            """Represent hashing completed media across the remaining deadline."""
            self.fixture.elapsed = 10801
            return {'TEST': 'snapshot'}
        with patch('studio.production.section_publication.attempt_reservation', self.history), \
                patch('studio.native_segments.reviews.assembly_snapshot', side_effect=snapshot):
            publish_delivery(self.request, result)
        actual = json.loads((root / 'delivery.json').read_text())
        self.assertEqual(actual['status'], 'failed')
        self.assertIn('deadline has passed', actual['error'])

    def test_commit_failure_preserves_file_and_reports_unresolved_authority(self) -> None:
        """A failed budget commit cannot mask its cause with a second exclusive file write."""
        root = Path(self.request['output'])
        root.mkdir()
        self.request['revision']['mode'] = 'initial-long'
        self.request['productionBudget'].update(attemptId=None, continuationOf='a' * 32)
        (root / 'revision-picture.json').write_text('{"sectionSnapshot":{"TEST":"snapshot"}}')
        result = {'status': 'native-long-checked-for-review', 'output': str(root / 'review.mp4'),
                  'sha256': 'c' * 64}
        with patch('studio.production.section_publication.attempt_reservation', self.history), \
                patch('studio.native_segments.reviews.assembly_snapshot', return_value={'TEST': 'snapshot'}), \
                patch('studio.production.section_publication.commit_publication',
                      side_effect=RuntimeError('TEST authority commit failed')):
            publish_delivery(self.request, result)
        saved = json.loads((root / 'delivery.json').read_text())
        self.assertEqual(saved['status'], 'native-long-checked-for-review')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failureCategory'], 'budget-authority-commit')
        self.assertIn('authority commit failed', result['error'])

    def test_checked_continuation_is_committed_before_lock_release(self) -> None:
        """The next contender sees the final debit before it can publish another file."""
        root = Path(self.request['output'])
        root.mkdir()
        self.request['revision']['mode'] = 'initial-long'
        self.request['productionBudget'].update(attemptId=None, continuationOf='a' * 32)
        (root / 'revision-picture.json').write_text('{"sectionSnapshot":{"TEST":"snapshot"}}')
        result = {'status': 'native-long-checked-for-review', 'output': str(root / 'review.mp4'),
                  'sha256': 'c' * 64}
        with patch('studio.production.section_publication.attempt_reservation', self.history), \
                patch('studio.native_segments.reviews.assembly_snapshot', return_value={'TEST': 'snapshot'}):
            publish_delivery(self.request, result)
        deliveries = self.fixture.record()['clips']['A']['deliveries']
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]['output'], result['output'])
        with self.assertRaisesRegex(RuntimeError, 'already has a checked delivery'):
            with section_publication(self.request):
                self.fail('A second unchecked promotion entered history')
