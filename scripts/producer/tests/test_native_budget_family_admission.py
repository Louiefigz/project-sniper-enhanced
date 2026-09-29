"""Real private family authority and frozen requests; preview bytes are synthetic."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_production_sections as sections_fixture
from _native_section_budget_fixture import SUPERVISOR
from cut_preview_io import write_new
from studio.native_budget_family import reserve_family, record_family_outcome
from studio.native_budget_family_state import verify_family_request
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_store import locked_batch
from studio.native_runtime import digest
from studio.native_review_regions import region_packet
from studio.native_long_scope import request_preview_windows
from studio.production.section_plan import pin_file
from studio.production.sections import bind_section_tasks


class FamilyAdmissionTests(unittest.TestCase):
    """Exercise public reservation and actual worker request guards against closed durable records."""

    def setUp(self) -> None:
        self.h = sections_fixture.ProductionSectionsTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.enterContext(patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1))
        self.engine = {'root': str(self.h.budget.base), 'identity': 'e' * 64, 'files': 1}
        self.enterContext(patch('studio.native_budget_family.engine_identity', return_value=self.engine))
        # P0 (X118): the preparation module binds both names when it is first imported, so it is patched
        # directly; otherwise this test passed only when it happened to import that module under these patches.
        for module in ('native_budget_launch', 'native_budget_family_reservation', 'native_budget_family_preparation'):
            self.enterContext(patch(f'studio.{module}.own_identity', return_value=SUPERVISOR))
        for module in ('native_budget_launch', 'native_budget_family_state', 'native_budget_family_preparation'):
            self.enterContext(patch(f'studio.{module}._process_table', return_value={7001: (1, 7001, 'TEST supervisor')}))
        record = self.h.budget.record()
        record['clips']['A']['attempts'] = []
        record['clips']['A']['counters']['exportAttempt'] = 0
        record['engine'] = self.engine
        self.h.budget.raw(record)  # Initial fixture construction, before any family reservation.
        project = self.h.fixture.project
        packet = self.h.budget.base / 'LONG-REQUEST.json'
        write_new(packet, {'sources': [{'sha256': 'f' * 64}]})
        file = project / 'LONG-PROJECT.json'
        plan = json.loads(file.read_text())
        plan['requestPacket'] = {'path': str(packet), 'sha256': digest(packet)}
        file.write_text(json.dumps(plan))
        self.h.request['pins'][str(file)] = digest(file)
        self.h.fixture.inputs[str(file)] = digest(file)
        for assignment in self.h.context['assignments']:
            self.h.complete(assignment['authorTaskId'])
        self.serial = 0

    def scope(self, section: str | None) -> dict | None:
        if section is None:
            return None
        row = next(row for row in self.h.context['assignments'] if row['sectionId'] == section)
        return {'schemaVersion': 1, **{key: row[key] for key in
                ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
                'sharedPlan': self.h.context['sharedPlan'], 'snapshotProject': str(self.h.fixture.project),
                'snapshotPinsHash': 'c' * 64}

    def reserve(self, section: str | None, preview: bool = True) -> dict:
        self.serial += 1
        output = self.h.budget.base / f'family-child-{self.serial}'
        scope = self.scope(section)
        grant = reserve_family(self.h.context, self.h.fixture.project, output,
                               {'sectionId': section, 'previewOnly': preview, 'snapshotScope': scope})
        output.mkdir()
        request = copy.deepcopy(self.h.request)
        request.update(output=str(output), productionBudget=grant, previewOnly=preview)
        if scope:
            request['sectionScope'] = scope
        bind_section_tasks(request, self.h.planfile)
        if section is None and preview:
            from studio.native_long_contract import family_preview_inventory
            request['sectionPreviewWindows'] = family_preview_inventory(self.h.fixture.project, self.h.context)[-1]['windows']
        write_new(output / 'export-request.json', request)
        return request

    def verify(self, request: dict, phase: str = 'preview') -> None:
        with locked_batch(self.h.budget.root, 'section-test') as session:
            record = session.read()
            verify_family_request(record, request, phase)
            session.commit(record, {'event': 'TEST-worker-admission'})

    def finish_preview(self, request: dict) -> None:
        root = Path(request['output'])
        packet = region_packet(request)
        clips = []
        for index, window in enumerate(request_preview_windows(request, packet)):
            file = root / f'TEST-preview-{index}.mp4'
            file.write_bytes(b'TEST nondecodable preview, not playback evidence')
            clips.append({**pin_file(file), 'absoluteFrameRange': [window['startFrame'], window['endFrame']]})
        file = root / 'motion-previews.json'
        write_new(file, {'status': 'native-motion-previews-complete', 'packet': packet,
                         'priorPreview': None, 'clips': clips})
        request_file = root / 'export-request.json'
        owner = self.h.fixture.owner_record(request, {str(request_file): digest(request_file)},
                                           'native-motion-previews-complete', str(file))
        write_new(root / 'preview.render.json', {**owner, 'completedAt': 'TEST completed'})
        record_family_outcome(request, {'status': 'native-motion-previews-complete'})

    def test_preview_children_and_join_share_one_counted_launch(self) -> None:
        requests = [self.reserve(section) for section in ('first', 'last')]
        self.assertEqual(len({row['productionBudget']['familyId'] for row in requests}), 1)
        for request in requests:
            self.verify(request)
            self.finish_preview(request)
        record = self.h.budget.record()
        self.assertEqual(record['clips']['A']['attempts'][0]['status'], 'running')
        joined = self.reserve(None)
        self.verify(joined, 'preview-picture-0')
        self.finish_preview(joined)
        record = self.h.budget.record()
        self.assertEqual(record['clips']['A']['counters']['previewLaunch'], 1)
        self.assertEqual(record['clips']['A']['sectionFamilies'][0]['state'], 'complete')
        self.assertEqual(record['clips']['A']['attempts'][0]['status'], 'succeeded')
        self.finish_preview_replay(joined)

    def finish_preview_replay(self, request: dict) -> None:
        before = self.h.budget.record()
        record_family_outcome(request, {'status': 'native-motion-previews-complete'})
        self.assertEqual(before, self.h.budget.record())

    def test_joined_preview_packages_charge_the_family_attempt(self) -> None:
        """(M-029d, M18) prepare_sections pre-charges every preview package; under the Long family binding
        (attemptId = the family id) each charge is admitted and counted on the family's attempt."""
        from studio.native_preview_sections import prepare_sections, section_windows
        for request in [self.reserve(section) for section in ('first', 'last')]:
            self.verify(request)
            self.finish_preview(request)
        joined = self.reserve(None)
        self.verify(joined, 'preview-picture-0')
        self.assertEqual(joined['productionBudget']['attemptId'], joined['productionBudget']['familyId'])
        pipeline = SimpleNamespace(request=joined, worker=lambda phase: None, supervise=lambda *args: None)
        with patch('studio.native_preview_recovery.restore_section', return_value=False), \
                patch('studio.native_preview_sections.seal_section'):
            prepare_sections(pipeline)
        clip = self.h.budget.record()['clips']['A']
        self.assertEqual(clip['counters'].get('previewPackage', 0), len(section_windows(joined)[1]))
        self.assertEqual(clip['attempts'][0]['status'], 'running')

    def test_duplicate_and_incomplete_integration_are_refused(self) -> None:
        first = self.reserve('first')
        with self.assertRaisesRegex(BudgetRefused, 'overlaps'):
            self.reserve('first')
        with self.assertRaisesRegex(BudgetRefused, 'overlaps'):
            self.reserve(None)
        self.finish_preview(first)
        with self.assertRaisesRegex(BudgetRefused, 'already succeeded'):
            self.reserve('first')
        with self.assertRaisesRegex(BudgetRefused, 'every required section'):
            self.reserve(None)

    def test_actual_worker_rejects_forged_route_scope_plan_and_expired_grant(self) -> None:
        request = self.reserve('first')
        for field in ('route', 'scope', 'plan'):
            forged = copy.deepcopy(request)
            if field == 'route':
                forged['productionBudget']['route'] = 'final'
            elif field == 'scope':
                forged['sectionScope']['frameRange'][1] -= 1
            else:
                forged['pins'][str(self.h.fixture.project / 'LONG-PROJECT.json')] = '0' * 64
            with self.assertRaises((BudgetRefused, ValueError)):
                self.verify(forged)
        record = self.h.budget.record()
        record['clock']['elapsed'] = 9999
        with self.assertRaisesRegex(BudgetRefused, 'grant expired'):
            verify_family_request(record, request, 'preview')

    def test_frozen_disk_request_cannot_forge_pins_scope_or_success_route(self) -> None:
        request = self.reserve('first')
        file = Path(request['output']) / 'export-request.json'
        for field in ('scope', 'plan', 'route'):
            forged = copy.deepcopy(request)
            if field == 'scope':
                forged['sectionScope']['snapshotPinsHash'] = '0' * 64
            elif field == 'plan':
                forged['pins'][str(self.h.fixture.project / 'LONG-PROJECT.json')] = '0' * 64
            else:
                forged['productionBudget']['route'] = 'final'
            file.write_text(json.dumps(forged))
            with self.assertRaises(BudgetRefused):
                record_family_outcome(forged, {'status': 'native-motion-previews-complete'})
        file.write_text(json.dumps(request))
        self.finish_preview(request)

    def test_final_children_share_export_and_picture_debits(self) -> None:
        from studio.native_budget_sections import SectionBudgetOwner
        requests = [self.reserve(section, False) for section in ('first', 'last')]
        self.assertEqual(len({row['productionBudget']['familyId'] for row in requests}), 1)
        owners = [SectionBudgetOwner(requests[0], 'segment-picture-0'),
                  SectionBudgetOwner(requests[1], 'segment-picture-2')]
        for owner in owners:
            owner.before_launch()
        clip = self.h.budget.record()['clips']['A']
        self.assertEqual(clip['counters']['exportAttempt'], 1)
        self.assertEqual(clip['counters']['pictureGeneration'], 1)
        with self.assertRaisesRegex(BudgetRefused, 'escaped'):
            SectionBudgetOwner(requests[0], 'segment-picture-2').before_launch()
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            record_family_outcome(requests[0], {'status': 'native-long-section-sealed-awaiting-integration'})
        for owner in owners:
            owner.complete({'status': 'native-segment-window-complete'})
        self.assertEqual(self.h.budget.record()['clips']['A']['attempts'][0]['status'], 'running')

    def test_success_after_deadline_refused_but_failure_settles(self) -> None:
        request = self.reserve('first')
        self.h.budget.elapsed = 9999
        with self.assertRaises(BudgetRefused):
            record_family_outcome(request, {'status': 'native-motion-previews-complete'})
        record_family_outcome(request, {'status': 'failed', 'failureCategory': 'budget-exhausted'})
        self.assertEqual(self.h.budget.record()['clips']['A']['sectionFamilies'][0]['invocations'][0]['status'], 'failed')

    def test_proof_hashing_cannot_outlive_original_success_grant(self) -> None:
        from studio import native_budget_family_outcome as outcomes
        request = self.reserve('first')
        original = outcomes.validate_outcome
        def hashes_cross_deadline(*args: object) -> bool:
            passed = original(*args)
            self.h.budget.elapsed = 9999
            return passed
        with patch.object(outcomes, 'validate_outcome', side_effect=hashes_cross_deadline):
            with self.assertRaisesRegex(BudgetRefused, 'original grant ended'):
                self.finish_preview(request)
        row = self.h.budget.record()['clips']['A']['sectionFamilies'][0]['invocations'][0]
        self.assertEqual(row['status'], 'running')
        record_family_outcome(request, {'status': 'failed', 'failureCategory': 'budget-exhausted'})

    def test_completion_proof_reads_finish_before_last_success_clock_check(self) -> None:
        from studio import native_budget_family_repair as repair
        request = self.reserve('first')
        original = repair.repair_state
        def late_completion_proof(*args: object, **kwargs: object) -> dict | None:
            result = original(*args, **kwargs)
            self.h.budget.elapsed = 9999
            return result
        with patch.object(repair, 'repair_state', side_effect=late_completion_proof):
            with self.assertRaisesRegex(BudgetRefused, 'original grant ended'):
                self.finish_preview(request)
        family = self.h.budget.record()['clips']['A']['sectionFamilies'][0]
        self.assertEqual(family['invocations'][0]['status'], 'running')
        self.assertEqual(family['state'], 'awaiting-sections')

    def test_transient_retry_is_single_shared_debit_and_deterministic_refuses(self) -> None:
        first = self.reserve('first')
        record_family_outcome(first, {'status': 'failed', 'failureCategory': 'host-memory-pressure'})
        retry = self.reserve('first')
        self.assertEqual(first['productionBudget']['familyId'], retry['productionBudget']['familyId'])
        self.assertEqual(self.h.budget.record()['clips']['A']['counters']['transientRetry'], 1)
        record_family_outcome(retry, {'status': 'failed', 'failureCategory': 'host-memory-pressure'})
        with self.assertRaisesRegex(BudgetRefused, 'already used'):
            self.reserve('first')
        other = self.reserve('last')
        record_family_outcome(other, {'status': 'failed', 'failureCategory': 'invalid-composition'})
        with self.assertRaisesRegex(BudgetRefused, 'deterministically'):
            self.reserve('last')


if __name__ == '__main__':
    unittest.main()
