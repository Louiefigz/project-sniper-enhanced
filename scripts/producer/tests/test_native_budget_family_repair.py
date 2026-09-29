"""Repair-family admission over registered saved sections; media and judgments remain TEST fixtures."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_production_scoped_repair as scoped
from _native_section_budget_fixture import SUPERVISOR
from cut_preview_io import write_new
from studio.native_budget_family import reserve_family, record_family_outcome
from studio.native_budget_family_repair import repair_state
from studio.native_budget_family_schema import ASSIGNMENT_KEYS
from studio.native_budget_registry import BudgetRefused
from studio.native_long_contract import family_preview_inventory
from studio.native_runtime import digest
from studio.production.section_plan import pin_file


class FamilyRepairTests(unittest.TestCase):
    """Construct a prior counted family, then run actual registered completion and new repair admission."""

    def setUp(self) -> None:
        self.f = scoped.ScopedRepairTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        h = self.f.h
        self.h = h
        self.engine = {'root': str(h.budget.base), 'identity': 'e' * 64, 'files': 1}
        self.enterContext(patch('studio.native_budget_family.engine_identity', return_value=self.engine))
        self.enterContext(patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1))
        self.enterContext(patch('studio.native_budget_launch.own_identity', return_value=SUPERVISOR))
        self.enterContext(patch('studio.native_budget_family_reservation.own_identity', return_value=SUPERVISOR))
        self.enterContext(patch('studio.native_budget_family_state._process_table',
                                return_value={7001: (1, 7001, 'TEST supervisor')}))
        packet = h.budget.base / 'LONG-REQUEST.json'
        write_new(packet, {'sources': [{'sha256': 'f' * 64}]})
        file = h.fixture.project / 'LONG-PROJECT.json'
        plan = json.loads(file.read_text())
        plan['requestPacket'] = {key: pin_file(packet)[key] for key in ('path', 'sha256')}
        file.write_text(json.dumps(plan))
        h.request['pins'][str(file)] = digest(file)
        record = h.budget.record()
        record['engine'] = self.engine
        family = self.parent_family()
        record['clips']['A']['sectionFamilies'] = [family]
        record['clips']['A']['attempts'][0].update(project=h.request['project'], output=h.request['output'])
        h.budget.raw(record)  # Prior-family fixture construction; subsequent transitions use public transactions.
        h.request['productionBudget'].update(route='final', familyId='a' * 32, familyInvocation='b' * 32,
            familyProject=h.request['project'], familyOutput=h.request['output'])
        h.preview = h.make_previews()
        self.original = self.f.initial()
        record_family_outcome(self.original, {'status': 'failed', 'failureCategory': 'section-review-pending'})
        self.packet = plan['requestPacket']
        with patch('test_production_scoped_repair.write_static_project', side_effect=self.repaired_project):
            self.f.repair(self.original)
        self.serial = 0

    def repaired_project(self, project: Path, canvas: dict, texts: tuple) -> Path:
        from _native_long_isolation_fixture import write_static_project
        result = write_static_project(project, canvas, texts)
        file = result / 'LONG-PROJECT.json'
        value = json.loads(file.read_text())
        value['requestPacket'] = self.packet
        file.write_text(json.dumps(value))
        return result

    def parent_family(self) -> dict:
        h = self.h
        row = {'id': 'b' * 32, 'sectionId': None, 'project': h.request['project'], 'output': h.request['output'],
               'planSha256': digest(h.fixture.project / 'LONG-PROJECT.json'), 'scopeSha256': None,
               'requestSha256': None, 'supervisor': SUPERVISOR, 'status': 'running', 'admittedElapsed': 0,
               'completedElapsed': None, 'resultStatus': None, 'resultIdentity': None, 'failure': None}
        return {'id': 'a' * 32, 'plan': h.context['plan'], 'sharedPlan': h.context['sharedPlan'],
                'assignments': [{key: item[key] for key in ASSIGNMENT_KEYS} for item in h.context['assignments']],
                'previewInventory': family_preview_inventory(h.fixture.project, h.context),
                'state': 'finalizing', 'invocations': [row]}

    def reserve(self, section: str = 'B', preview: bool = True) -> dict:
        h = self.h
        row = next(row for row in h.context['assignments'] if row['sectionId'] == section)
        scope = {'schemaVersion': 1, **{key: row[key] for key in
                ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
                'sharedPlan': h.context['sharedPlan'], 'snapshotProject': str(h.fixture.project),
                'snapshotPinsHash': 'c' * 64}
        self.serial += 1
        return reserve_family(h.context, h.fixture.project, h.budget.base / f'repair-child-{self.serial}',
                              {'sectionId': section, 'previewOnly': preview, 'snapshotScope': scope,
                               'parentAttempt': Path(self.original['output'])})

    def test_repair_retains_real_a_c_proofs_and_original_grant_end(self) -> None:
        self.h.budget.elapsed = 100
        grant = self.reserve()
        clip = self.h.budget.record()['clips']['A']
        old, new = clip['attempts']
        self.assertEqual(old['status'], 'failed')
        self.assertEqual(old['failure']['category'], 'section-plan-repaired')
        self.assertLessEqual(new['admittedElapsed'] + new['grantedSeconds'], 9000)
        self.assertEqual(clip['counters']['exportAttempt'], 1)
        self.assertEqual(clip['counters']['previewLaunch'], 1)
        family = clip['sectionFamilies'][-1]
        self.assertEqual([row['sectionId'] for row in family['invocations']], ['B'])
        self.assertEqual(grant['familyId'], new['id'])
        with self.assertRaisesRegex(BudgetRefused, 'Unchanged'):
            self.reserve('A')

    def test_repair_final_is_second_counted_export_and_cannot_extend_grant(self) -> None:
        self.h.budget.elapsed = 500
        grant = self.reserve(preview=False)
        clip = self.h.budget.record()['clips']['A']
        attempt = next(row for row in clip['attempts'] if row['id'] == grant['attemptId'])
        self.assertEqual(clip['counters']['exportAttempt'], 2)
        self.assertLessEqual(attempt['admittedElapsed'] + attempt['grantedSeconds'], 9000)
        self.assertEqual(clip['counters']['author'], 3)
        self.assertEqual(clip['counters']['repairCycle'], 1)
        self.assertEqual(clip['counters']['review'], 6)

    def test_original_grant_expiry_refuses_new_family(self) -> None:
        self.h.budget.elapsed = 9001
        with self.assertRaises((ValueError, RuntimeError)):
            self.reserve()
        self.assertEqual(self.h.budget.record()['clips']['A']['counters']['previewLaunch'], 0)

    def test_actual_repair_closure_hashing_cannot_finish_after_original_grant(self) -> None:
        from types import SimpleNamespace
        import test_native_budget_family_admission as admitted
        from studio import native_budget_family_repair as repair
        from studio.production.sections import bind_section_tasks
        grant = self.reserve()
        output = Path(grant['familyOutput'])
        output.mkdir()
        row = self.h.context['assignments'][1]
        scope = {'schemaVersion': 1, **{key: row[key] for key in
                ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
                'sharedPlan': self.h.context['sharedPlan'], 'snapshotProject': str(self.h.fixture.project),
                'snapshotPinsHash': 'c' * 64}
        request = {**copy.deepcopy(self.h.request), 'output': str(output), 'productionBudget': grant,
                   'sectionScope': scope, 'previewOnly': True}
        bind_section_tasks(request, self.h.planfile)
        write_new(output / 'export-request.json', request)
        original = repair.repair_state
        def cross_after_real_hashes(*args: object, **kwargs: object) -> dict:
            state = original(*args, **kwargs)
            self.assertEqual(state['retained'], {'A', 'C'})
            self.h.budget.elapsed = 9999
            return state
        with patch.object(repair, 'repair_state', side_effect=cross_after_real_hashes):
            with self.assertRaisesRegex(BudgetRefused, 'original grant ended'):
                admitted.FamilyAdmissionTests.finish_preview(SimpleNamespace(h=self.h), request)
        family = self.h.budget.record()['clips']['A']['sectionFamilies'][-1]
        self.assertEqual(family['invocations'][0]['status'], 'running')
        self.assertEqual(family['state'], 'awaiting-sections')

    def test_live_parent_fences_repair_without_spending_counters(self) -> None:
        record = self.h.budget.record()
        row = record['clips']['A']['sectionFamilies'][0]['invocations'][0]
        row.update(status='running', completedElapsed=None, resultStatus=None, resultIdentity=None, failure=None)
        self.h.budget.raw(record)
        with self.assertRaisesRegex(BudgetRefused, 'live family'):
            self.reserve()
        self.assertEqual(self.h.budget.record()['clips']['A']['counters']['previewLaunch'], 0)

    def test_changed_saved_media_or_unchanged_source_closure_refuses(self) -> None:
        file = Path(self.original['output']) / 'segment-picture-0-TEST.mp4'
        before = file.read_bytes()
        file.write_bytes(b'TEST tampered original A')
        with self.assertRaises((ValueError, RuntimeError)):
            self.reserve()
        file.write_bytes(before)
        component = self.h.fixture.project / 'compositions/unit-0.html'
        component.write_text(component.read_text().replace('A', 'tampered A'))
        with self.assertRaises((ValueError, RuntimeError)):
            self.reserve()
        self.assertEqual(self.h.budget.record()['clips']['A']['counters']['previewLaunch'], 0)


if __name__ == '__main__':
    unittest.main()
