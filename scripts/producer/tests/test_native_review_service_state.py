"""Cold service facts use registered review authority; media is explicit TEST data."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import test_production_chunk_carry_dispatch as fixtures
import test_native_review_service_family as service_fixtures
from native_work_service_rates import RateCatalog
from studio.native_segments.review_service_family import family_service
from studio.native_runtime import digest
from studio.native_segments.review_scopes import package_scopes, phase_for
from native_work_service_pins import identity
from studio.native_segments.review_service_state import cold_family_state, request_facts
from studio.production import api


class FamilyAuthorityTests(unittest.TestCase):
    """Forecast facts cannot borrow an unregistered family or preview completion."""

    def test_registered_final_family_required_for_completion_reductions(self) -> None:
        """The same durable family must exist in the caller's locked production record."""
        family = {'id': 'TEST-family', 'state': 'awaiting-sections', 'invocations': []}
        evidence = {'identity': identity({})}
        record = {'clips': {'A': {'sectionFamilies': [], 'attempts': []}}}
        with self.assertRaisesRegex(ValueError, 'not registered'):
            cold_family_state(record, family, evidence)
        record['clips']['A'].update(sectionFamilies=[family], attempts=[{'id': family['id'], 'route': 'preview'}])
        with self.assertRaisesRegex(ValueError, 'preview outcomes'):
            cold_family_state(record, family, evidence)
        record['clips']['A']['attempts'][0]['route'] = 'final'
        state = cold_family_state(record, family, evidence)
        self.assertEqual(state['members'], {})
        self.assertFalse(state['hasMedia'])


class ServiceStateTests(unittest.TestCase):
    """Validate forecast reductions against real authority, receipts and present corruption."""

    def setUp(self) -> None:
        """Use the current registered repair fixture with fictional codec/editorial content."""
        self.case = fixtures.ChunkCarryDispatchTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.host
        self.request = self.host.request
        self.evidence = {'scopes': package_scopes(self.request)}

    def facts(self) -> dict:
        """Reopen actual current state without an estimate or a callback mutation."""
        return request_facts(self.host.budget.record(), self.request, self.evidence)

    def remove_test_package(self, scope_id: str) -> None:
        """Model an uncreated derived package; preserve all current window/media evidence."""
        root = Path(self.request['output'])
        phase = phase_for(scope_id)
        for suffix in ('.json', '-stage.json'):
            file = root / f'{phase}{suffix}'
            if file.exists():
                file.unlink()

    def test_live_withdrawal_restores_package_demand_without_discarding_seals(self) -> None:
        """Old review withdrawal changes only eligibility; original claim charges and media survive."""
        self.case.dispatch()
        before = self.facts()
        self.assertEqual(before['coveredScopes'], {row['id'] for row in self.evidence['scopes']})
        self.assertTrue(before['completedSections'] <= before['coveredSections'])
        self.assertEqual(len(before['carry']), 2)
        for scope_id in before['carry']:
            self.remove_test_package(scope_id)
        root = Path(self.request['output'])
        seals = {file: digest(file) for file in root.glob('segment-picture-*-stage.json')}
        counters = copy.deepcopy(self.host.budget.record()['clips']['A']['counters'])
        preserved = self.facts()
        self.assertEqual(preserved['carry'], before['carry'])
        self.assertFalse(preserved['packages'] & before['carry'])
        api.supersede_task(self.host.budget.root, 'section-test', self.case.original['id'],
                           'TEST explicit independent review withdrawal')
        after = self.facts()
        self.assertFalse(after['carry'])
        self.assertFalse(after['packages'] & before['carry'])
        self.assertEqual(after['pendingWindows'], 0)
        self.assertEqual({file: digest(file) for file in seals}, seals)
        self.assertEqual(self.host.budget.record()['clips']['A']['counters'], counters)
        reviewer = self.case.attach()
        receipt = reviewer.progress(1)
        reviewer.record(receipt)
        progressed = self.facts()
        self.assertEqual(len(progressed['progress']), 1)
        self.assertEqual(progressed['pendingWindows'], 0)
        damaged = next(iter(seals))
        damaged.write_bytes(b'TEST corrupted present current seal')
        with self.assertRaises((ValueError, RuntimeError)):
            self.facts()

    def test_required_repair_donor_missing_still_refuses(self) -> None:
        """Pruning forecast roots never bypasses a current window's real donor closure."""
        before = self.facts()
        self.assertEqual(before['pendingWindows'], 0)
        phase = 'segment-picture-0'
        (Path(self.request['output']) / f'{phase}-stage.json').unlink()
        donor = Path(self.request['revision']['windowDonors'][phase])
        donor.unlink()
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.facts()


class RequestSupersessionTests(unittest.TestCase):
    """Test cold-fact aggregation with explicit TEST reader outputs, not fabricated seals."""

    def setUp(self) -> None:
        """Use real frozen geometry and fallback rates; isolate only immutable request reads."""
        self.fixture = service_fixtures.FamilyServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.evidence = self.fixture.evidence
        self.local = [row for row in self.evidence['scopes'] if len(row['sectionIds']) == 1]

    def facts(self, scopes: list[dict], complete: bool = False) -> dict:
        """Represent a reader's explicit covered inventory and compatible completion facts."""
        ids = {row['id'] for row in scopes}
        sections = {item for row in scopes for item in row['sectionIds']}
        return {'pendingWindows': 0, 'packages': set(ids) if complete else set(),
                'progress': set(ids) if complete else set(), 'carry': set(),
                'completedSections': set(sections) if complete else set(), 'hasMedia': True,
                'coveredScopes': ids, 'coveredSections': sections}

    def state(self, invocations: list[dict], facts: list[dict | None | Exception]) -> dict:
        """Keep registration and forecast derivation real while supplying bounded read results."""
        family = {'id': 'TEST-final', 'state': 'awaiting-sections', 'invocations': invocations}
        record = {'clips': {'A': {'sectionFamilies': [family],
                                  'attempts': [{'id': family['id'], 'route': 'final'}]}}}
        before = copy.deepcopy(record)
        def read_request(_family: dict, invocation: dict) -> dict | None:
            """Missing TEST paths raise only if the production selector actually opens them."""
            index = next(index for index, row in enumerate(invocations) if row is invocation)
            value = facts[index]
            if isinstance(value, Exception):
                raise value
            return {'TEST-facts': value} if value is not None else None

        with patch('studio.native_segments.review_service_state.registered_request', side_effect=read_request) as read, \
                patch('studio.native_segments.review_service_state.request_facts',
                      side_effect=lambda _record, request, _evidence: request['TEST-facts']):
            result = cold_family_state(record, family, self.evidence)
        self.opened = [call.args[1] for call in read.call_args_list]
        self.assertEqual(record, before)
        return result

    def test_current_integrated_miss_restores_317_second_package_forecast(self) -> None:
        """An old private package cannot mask a current full request's incompatible master."""
        scope = self.local[0]
        section = scope['sectionIds'][0]
        old = self.facts([scope], complete=True)
        current = self.facts(self.evidence['scopes'])
        state = self.state([{'sectionId': section, 'status': 'succeeded'},
                            {'sectionId': None, 'status': 'active'}], [old, current])
        self.assertFalse(state['packages'] | state['progress'] | state['completedSections'])
        fixed = family_service(self.evidence, RateCatalog(), state, None)
        stale = copy.deepcopy(state)
        stale['packages'].add(scope['id'])
        broken = family_service(self.evidence, RateCatalog(), stale, None)
        key = next(row['key'] for row in self.evidence['readPlan']['calls']
                   if row['scopeId'] == scope['id'] and row['site'] == 'package-create')
        self.assertEqual(fixed['remaining']['calls'][key], 1)
        self.assertEqual(broken['remaining']['calls'][key], 0)
        self.assertAlmostEqual(fixed['seconds'] - broken['seconds'], 317.5)

    def test_same_section_replacement_clears_old_carry_and_preserves_uncovered_scopes(self) -> None:
        """A newer private request replaces its own reductions without erasing a sibling's work."""
        first = self.local[0]
        sibling = next(row for row in self.local if row['sectionIds'] != first['sectionIds'])
        old, other, current = self.facts([first], True), self.facts([sibling], True), self.facts([first])
        old['carry'].add(first['id'])
        state = self.state([{'sectionId': first['sectionIds'][0], 'status': 'succeeded'},
                            {'sectionId': sibling['sectionIds'][0], 'status': 'succeeded'},
                            {'sectionId': first['sectionIds'][0], 'status': 'active'}], [old, other, current])
        self.assertEqual(state['packages'], {sibling['id']})
        self.assertEqual(state['progress'], {sibling['id']})
        self.assertEqual(state['completedSections'], set(sibling['sectionIds']))
        self.assertFalse(state['carry'])
        self.assertEqual(state['additionalDemand'], ['recovery'])
        self.assertEqual(family_service(self.evidence, RateCatalog(), state)['status'], 'fallback')


    def test_unbound_full_invocation_restores_transferred_package_forecast(self) -> None:
        """Pre-owner admission cannot presume the unpublished integrated master is compatible."""
        scope = self.local[0]
        state = self.state([{'sectionId': scope['sectionIds'][0], 'status': 'succeeded'},
                            {'sectionId': None, 'status': 'running'}], [self.facts([scope], True), None])
        self.assertIsNone(state['members'][None]['facts'])
        self.assertFalse(state['packages'] | state['progress'] | state['completedSections'])
        fixed = family_service(self.evidence, RateCatalog(), state, None)
        stale = copy.deepcopy(state)
        stale['packages'].add(scope['id'])
        broken = family_service(self.evidence, RateCatalog(), stale, None)
        self.assertEqual(fixed['status'], 'fallback')
        self.assertAlmostEqual(fixed['seconds'] - broken['seconds'], 317.5)

    def test_unbound_private_invocation_clears_only_its_frozen_coverage(self) -> None:
        """Unknown replacement media restores its work while preserving uncovered sibling facts."""
        first = self.local[0]
        sibling = next(row for row in self.local if row['sectionIds'] != first['sectionIds'])
        old, other = self.facts([first], True), self.facts([sibling], True)
        old['carry'].add(first['id'])
        state = self.state([{'sectionId': first['sectionIds'][0], 'status': 'succeeded'},
                            {'sectionId': sibling['sectionIds'][0], 'status': 'succeeded'},
                            {'sectionId': first['sectionIds'][0], 'status': 'running'}], [old, other, None])
        self.assertEqual(state['packages'], {sibling['id']})
        self.assertEqual(state['progress'], {sibling['id']})
        self.assertEqual(state['completedSections'], set(sibling['sectionIds']))
        self.assertFalse(state['carry'])
        remaining = family_service(self.evidence, RateCatalog(), state, first['sectionIds'][0])
        key = next(row['key'] for row in self.evidence['readPlan']['calls']
                   if row['scopeId'] == first['id'] and row['site'] == 'package-create')
        self.assertEqual(remaining['remaining']['calls'][key], 1)

    def test_latest_full_skips_missing_obsolete_private_and_full_requests(self) -> None:
        """Missing irrelevant history cannot fail current state or erase original retry metadata."""
        section = self.local[0]['sectionIds'][0]
        invocations = [{'sectionId': section, 'status': 'failed'},
                       {'sectionId': None, 'status': 'succeeded'},
                       {'sectionId': None, 'status': 'running'}]
        absent = FileNotFoundError('TEST obsolete output is absent')
        state = self.state(invocations, [absent, absent, self.facts(self.evidence['scopes'])])
        self.assertEqual(self.opened, [invocations[-1]])
        self.assertEqual(state['additionalDemand'], ['recovery', 'retry'])
        self.assertFalse(state['members'][section]['terminal'])
        self.assertIsNone(state['members'][section]['facts'])
        self.assertFalse(state['packages'])
        state = self.state(invocations, [absent, absent, None])
        self.assertEqual(self.opened, [invocations[-1]])
        self.assertFalse(state['hasMedia'])

    def test_latest_private_skips_only_same_section_and_keeps_required_full(self) -> None:
        """Uncovered global/sibling facts still require the original full request and its proofs."""
        first = self.local[0]
        sibling = next(row for row in self.local if row['sectionIds'] != first['sectionIds'])
        invocations = [{'sectionId': first['sectionIds'][0], 'status': 'succeeded'},
                       {'sectionId': None, 'status': 'succeeded'},
                       {'sectionId': first['sectionIds'][0], 'status': 'running'}]
        absent = FileNotFoundError('TEST required current proof is absent')
        current = self.facts([first])
        state = self.state(invocations, [absent, self.facts([sibling], True), current])
        self.assertEqual(self.opened, invocations[1:])
        self.assertEqual(state['packages'], {sibling['id']})
        with self.assertRaisesRegex(FileNotFoundError, 'required current proof'):
            self.state(invocations, [absent, absent, current])
        with self.assertRaisesRegex(FileNotFoundError, 'required current proof'):
            self.state(invocations, [absent, self.facts([sibling], True), absent])


if __name__ == '__main__':
    unittest.main()
