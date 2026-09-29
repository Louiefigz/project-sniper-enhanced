"""Section owners preserve counted wall time and launch charges across failures and resumes."""
from __future__ import annotations

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from _native_section_budget_fixture import SectionBudgetFixture
from studio.native_budget_clock import BudgetExhausted, allocation_remaining
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_sections import SectionBudgetOwner
from studio.native_budget_store import BudgetAuthorityError


class SectionBudgetTests(unittest.TestCase):
    """Real durable transactions; only clock/process observation is controlled."""

    def setUp(self) -> None:
        """Use a private store for every test."""
        self.fixture = SectionBudgetFixture(self)

    def owner(self, index: int = 0) -> SectionBudgetOwner:
        """One owner with one immutable debit token."""
        return SectionBudgetOwner(self.fixture.request, f'segment-picture-{index}')

    def test_queue_without_owned_launch_never_debits(self) -> None:
        """Waiting/failed admission creates no phase attempt or counter."""
        self.owner().complete({'status': 'failed', 'failureCategory': 'capacity-timeout'})
        clip = self.fixture.record()['clips']['A']
        self.assertNotIn('sectionOwners', clip)
        self.assertEqual(clip['counters']['pictureGeneration'], 0)

    def test_concurrent_sections_debit_one_picture_generation(self) -> None:
        """Separate pool-admitted owners serialize one shared generation charge."""
        owners = [self.owner(0), self.owner(1)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            grants = list(executor.map(lambda owner: owner.before_launch(), owners))
        clip = self.fixture.record()['clips']['A']
        self.assertEqual((len(clip['sectionOwners']), clip['counters']['pictureGeneration']), (2, 1))
        self.assertEqual(grants[0], grants[1])

    def test_duplicate_live_same_section_cannot_debit(self) -> None:
        """Competing duplicate work is refused, not treated as another free section."""
        self.owner().before_launch()
        with self.assertRaisesRegex(BudgetRefused, 'live owned launch'):
            self.owner().before_launch()
        self.assertEqual(len(self.fixture.record()['clips']['A']['sectionOwners']), 1)

    def test_same_callback_token_is_idempotent(self) -> None:
        """An uncertain returned admission never debits twice."""
        owner = self.owner()
        owner.before_launch()
        self.fixture.elapsed = 30
        self.assertEqual(allocation_remaining(owner.before_launch()), 8970)
        self.assertEqual(len(self.fixture.record()['clips']['A']['sectionOwners']), 1)

    def test_deterministic_failure_cannot_retry_unchanged_inputs(self) -> None:
        """A fresh Python object or process does not erase a deterministic error."""
        owner = self.owner()
        owner.before_launch()
        owner.complete({'status': 'failed', 'failureCategory': 'renderer-failure'})
        with self.assertRaisesRegex(BudgetRefused, 'deterministic'):
            self.owner().before_launch()
        self.assertEqual(len(self.fixture.record()['clips']['A']['sectionOwners']), 1)

    def test_transient_retry_is_shared_and_durable(self) -> None:
        """The original one-retry limit survives completed failures."""
        for _ in range(2):
            owner = self.owner()
            owner.before_launch()
            owner.complete({'status': 'failed', 'failureCategory': 'host-memory-pressure'})
        with self.assertRaisesRegex(BudgetRefused, 'transient-failure retry'):
            self.owner().before_launch()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['transientRetry'], 1)

    def test_crash_stays_charged_and_uses_retry(self) -> None:
        """A supervisor that vanished is abandoned only on an actual absent identity proof."""
        self.owner().before_launch()
        with mock.patch('studio.native_budget_sections._process_table', return_value={}):
            self.owner().before_launch()
        clip = self.fixture.record()['clips']['A']
        self.assertEqual([row['status'] for row in clip['sectionOwners']], ['abandoned', 'running'])
        self.assertEqual(clip['counters']['transientRetry'], 1)

    def test_elapsed_review_restart_and_exhaustion_preserve_sections(self) -> None:
        """Waiting consumes the original grant while finished sections remain recorded."""
        owner = self.owner()
        owner.before_launch()
        owner.complete({'status': 'native-segment-window-complete'})
        self.fixture.elapsed = 8956
        with self.assertRaises(BudgetExhausted):
            self.owner(1).before_launch()
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(len(clip['sectionOwners']), 1)
        self.assertEqual(clip['sectionOwners'][0]['status'], 'succeeded')
        self.assertEqual(self.fixture.record()['clock']['elapsed'], 8956)

    def test_compatible_copy_does_not_debit_picture_generation(self) -> None:
        """Saved pictures still run governed copy/audio/QC work without picture spending."""
        self.fixture.request['revision']['windowDonors'] = {'segment-picture-0': '/TEST/seal.json'}
        self.owner().before_launch()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 0)

    def new_attempt(self) -> None:
        """Simulate the already-reserved second counted export on the same original authority."""
        record = self.fixture.record()
        clip = record['clips']['A']
        clip['attempts'][0].update(status='succeeded', completedElapsed=0)
        second = self.fixture.attempt()
        second.update(id='b' * 32, output=str(self.fixture.base / 'second'))
        clip['attempts'].append(second)
        clip['counters']['exportAttempt'] = 2
        self.fixture.raw(record)
        self.fixture.request['productionBudget']['attemptId'] = second['id']
        self.fixture.request['output'] = second['output']

    def test_missing_never_completed_window_reuses_original_generation(self) -> None:
        """Resuming unfinished C after saved A does not buy another picture generation."""
        first = self.owner()
        first.before_launch()
        first.complete({'status': 'native-segment-window-complete'})
        self.new_attempt()
        self.owner(1).before_launch()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 1)

    def test_rerender_completed_windows_charges_once_for_new_attempt(self) -> None:
        """Repeating saved picture work spends the second generation once across all windows."""
        for index in range(2):
            owner = self.owner(index)
            owner.before_launch()
            owner.complete({'status': 'native-segment-window-complete'})
        self.new_attempt()
        for index in range(2):
            self.owner(index).before_launch()
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(clip['counters']['pictureGeneration'], 2)
        self.assertEqual(clip['attempts'][1]['nested']['pictureGeneration'], 1)

    def test_schema_five_lift_preserves_original_authority(self) -> None:
        """An additive reader upgrade cannot reset original clocks, policies or counters."""
        record = self.fixture.record()
        record['schemaVersion'] = 5
        record['clips']['A']['counters']['review'] = 3
        self.fixture.raw(record)
        expected = copy.deepcopy(record)
        from studio.native_budget_schema import SCHEMA_VERSION
        expected['schemaVersion'] = SCHEMA_VERSION
        self.assertEqual(self.fixture.record(), expected)

    def test_schema_five_with_invented_section_history_is_rejected(self) -> None:
        """The lift validates the old closed shape before introducing new fields."""
        record = self.fixture.record()
        record['schemaVersion'] = 5
        record['clips']['A']['sectionOwners'] = []
        self.fixture.raw(record)
        with self.assertRaises(BudgetAuthorityError):
            self.fixture.record()


if __name__ == '__main__':
    unittest.main()
