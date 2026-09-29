"""Record-size admission leaves technical section owners durable terminal room."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from _native_section_budget_fixture import SectionBudgetFixture
from studio import native_budget_store as store
from studio.native_budget_sections import SectionBudgetOwner
from studio.production.settlement import DELIVERY_ENTRY_BYTES, _review_delivery_room, _section_owner_room, settlement_reserve
from studio.native_budget_continuation import apply_review_outcome


class SectionSettlementRoomTests(unittest.TestCase):
    """Use the real authority writer and bounded Unicode failure encoding."""

    def setUp(self) -> None:
        """Create parallel admitted owners under a private original Long attempt."""
        self.fixture = SectionBudgetFixture(self)
        self.owners = [SectionBudgetOwner(self.fixture.request, f'segment-picture-{index}') for index in range(2)]
        for owner in self.owners:
            owner.before_launch()

    def test_reserve_counts_every_running_section_owner(self) -> None:
        """The same-state delta equals every technical owner's widest terminal growth."""
        record = self.fixture.record()
        rows = record['clips']['A']['sectionOwners']
        settled = copy.deepcopy(record)
        for row in settled['clips']['A']['sectionOwners']:
            row.update(status='succeeded', completedElapsed=0)
        self.assertEqual(settlement_reserve(record) - settlement_reserve(settled),
                         sum(_section_owner_room(row) for row in rows))

    def test_full_record_still_accepts_all_terminal_section_failures(self) -> None:
        """Wide escaped text can settle after the next ordinary authority change is refused."""
        record = self.fixture.record()
        limit = len(store.canonical(record)) + settlement_reserve(record) - 1
        with mock.patch.object(store, 'MAX_RECORD_BYTES', limit):
            with store.locked_batch(self.fixture.root, 'section-test') as session:
                with self.assertRaisesRegex(store.BudgetAuthorityError, 'no room'):
                    session.commit(session.read(), {'event': 'new-work'})
            for owner in self.owners:
                owner.complete({'status': 'failed', 'failureCategory': '\U0001F600' * 4096,
                                'errorType': '\U0001F600' * 4096, 'abortReason': '\U0001F600' * 4096})
        result = self.fixture.record()
        self.assertLessEqual(len(store.canonical(result)), limit)
        self.assertTrue(all(row['status'] == 'failed' for row in result['clips']['A']['sectionOwners']))
        self.assertEqual(result['clips']['A']['counters']['pictureGeneration'], 1)

    def test_pending_review_retains_terminal_delivery_room(self) -> None:
        """A settled original keeps final-receipt space while reviewers work and other tasks fill authority."""
        for owner in self.owners:
            owner.complete({'status': 'native-segment-window-complete'})
        record = self.fixture.record()
        clip = record['clips']['A']
        self.assertEqual(_review_delivery_room(clip), 0)
        clip['attempts'][0].update(status='succeeded', completedElapsed=0)
        self.assertEqual(_review_delivery_room(clip), DELIVERY_ENTRY_BYTES)
        self.fixture.raw(record)
        limit = len(store.canonical(record)) + settlement_reserve(record) - 1
        request = {**self.fixture.request, 'productionBudget': {
            **self.fixture.request['productionBudget'], 'attemptId': None, 'continuationOf': 'a' * 32}}
        result = {'status': 'native-long-checked-for-review', 'output': '/' + 'x' * 4093, 'sha256': 'e' * 64}
        with mock.patch.object(store, 'MAX_RECORD_BYTES', limit):
            with store.locked_batch(self.fixture.root, 'section-test') as session:
                current = session.read()
                with self.assertRaisesRegex(store.BudgetAuthorityError, 'no room'):
                    session.commit(current, {'event': 'new-work'})
                event = apply_review_outcome(current, request, result, 0)
                session.commit(current, event)
        self.assertEqual(_review_delivery_room(self.fixture.record()['clips']['A']), 0)

    def test_missing_attempts_is_closed_schema_refusal(self) -> None:
        """Malformed old fields must refuse cleanly before additive section validation indexes them."""
        record = self.fixture.record()
        del record['clips']['A']['attempts']
        self.fixture.raw(record)
        with self.assertRaises(store.BudgetAuthorityError):
            self.fixture.record()


if __name__ == '__main__':
    unittest.main()
