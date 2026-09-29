"""Real private service bindings and family admission; TEST geometry is never a measured rate."""
from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

import test_native_budget_family_admission as families
import test_native_long_chunk_admission as chunks
from studio.native_budget_family_schema import family_ok, service_ok
from studio.native_budget_registry import BudgetRefused, project_identity
from studio.native_budget_store import locked_batch
from studio.native_segments import review_service_binding as binding
from studio.native_segments.long_plan import identity


class ServiceBindingTests(unittest.TestCase):
    """Use actual locked persistence/admission, mocking only prospective scope geometry."""

    def setUp(self) -> None:
        """Construct existing real authority; its short synthetic project has no chunk contract."""
        self.case = families.FamilyAdmissionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.h
        self.context = self.host.context
        self.project = self.host.fixture.project
        self.enterContext(patch('studio.native_segments.review_service.planned_inventory',
                                side_effect=self.fixture_inventory))
        self.value = binding.planned_binding(self.project, self.context)

    def fixture_inventory(self, project: Path, context: dict) -> tuple:
        """Supply explicitly TEST scopes; production persistence and estimator stay real."""
        self.assertEqual((project, context), (self.project, self.context))
        revision = self.host.request['revision']
        windows = revision['renderWindows']
        scopes = []
        for row in context['assignments']:
            start, end = row['frameRange']
            selected = [window for window in windows if start <= window['startFrame'] < end]
            scopes.append({'id': 'TEST-' + row['sectionId'], 'kind': 'chunk', 'sectionIds': [row['sectionId']],
                           'frameRange': [start, end], 'frames': end - start, 'seconds': (end - start) / 25,
                           'windows': len(selected), 'windowRanges': [[w['startFrame'], w['endFrame']] for w in selected]})
        return revision['canvas'], scopes, windows

    def freeze(self) -> dict:
        """Create an unreferenced immutable artifact through its actual held batch transaction."""
        with locked_batch(self.host.budget.root, 'section-test') as session:
            return binding.freeze_binding(session, self.context, self.value)

    def read(self, pin: dict, context: dict | None = None) -> dict:
        """Use the real private no-follow reader, not a synthetic pin acceptance."""
        with locked_batch(self.host.budget.root, 'section-test') as session:
            return binding.read_binding(session, context or self.context, pin)

    def test_private_sidecar_reuses_exact_file_and_rejects_hash_or_missing_bytes(self) -> None:
        """Replay preserves the immutable inode; declared corrupt/absent evidence has no fallback."""
        pin = self.freeze()
        file = Path(pin['envelope']['path'])
        before = file.stat()
        self.assertEqual(pin, self.freeze())
        self.assertEqual((file.stat().st_ino, file.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), pin['envelope']['sha256'])
        self.assertEqual(self.read(pin), self.value['envelope'])
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        file.write_bytes(file.read_bytes() + b' ')
        with self.assertRaises((ValueError, RuntimeError)):
            self.read(pin)
        with self.assertRaises((ValueError, RuntimeError)):
            self.freeze()
        file.unlink()
        with self.assertRaises((FileNotFoundError, ValueError, RuntimeError)):
            self.read(pin)

    def test_batch_and_authority_identity_cannot_borrow_private_sidecar(self) -> None:
        """Even a valid digest cannot be read under another batch, clip, or plan."""
        pin = self.freeze()
        for update in ({'batchId': 'another-batch'}, {'clipId': 'another-long'},
                       {'sharedPlan': {**self.context['sharedPlan'], 'sha256': '0' * 64}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.read(pin, self.context | update)

    def test_optional_schema_is_shape_only_and_preserves_legacy_rows(self) -> None:
        """Schema validation does not read the sidecar or grant byte-level eligibility."""
        request = self.case.reserve('first')
        record = self.host.budget.record()
        clip = record['clips']['A']
        family = clip['sectionFamilies'][0]
        attempts = {row['id']: row for row in clip['attempts']}
        pin = family['reviewService']
        Path(pin['envelope']['path']).unlink()
        with patch.object(binding, 'read_binding', side_effect=AssertionError('schema performed IO')), \
                patch('os.open', side_effect=AssertionError('schema opened a file')):
            self.assertTrue(service_ok(pin))
            self.assertTrue(family_ok(family, attempts))
            legacy = {key: value for key, value in family.items() if key != 'reviewService'}
            self.assertTrue(family_ok(legacy, attempts))
            self.assertFalse(service_ok(pin | {'extra': True}))
            self.assertFalse(service_ok(pin | {'schemaVersion': True}))
            self.assertFalse(family_ok(family | {'reviewService': pin | {'schemaVersion': True}}, attempts))
        self.assertEqual(request['productionBudget']['familyId'], family['id'])

    def test_preview_and_final_inherit_one_pin_without_creative_identity_change(self) -> None:
        """Operational evidence does not alter the project, shared plan, or launch identity."""
        before_project, before_context = project_identity(self.project), copy.deepcopy(self.context)
        preview = self.case.reserve('first')
        self.case.verify(preview)
        self.case.finish_preview(preview)
        replacement = copy.deepcopy(self.value)
        replacement['envelope']['knownInputs']['basis'] = 'TEST different later operational observation'
        body = {key: value for key, value in replacement['envelope'].items() if key != 'identity'}
        replacement['envelope']['identity'] = identity(body)
        with patch.object(binding, 'planned_binding', return_value=replacement):
            final = self.case.reserve('first', False)
        record = self.host.budget.record()
        clip = record['clips']['A']
        self.assertEqual(len(clip['sectionFamilies']), 2)
        self.assertEqual(clip['sectionFamilies'][0]['reviewService'], clip['sectionFamilies'][1]['reviewService'])
        self.assertEqual(self.read(clip['sectionFamilies'][1]['reviewService']), self.value['envelope'])
        self.assertEqual((project_identity(self.project), self.context), (before_project, before_context))
        for attempt in clip['attempts']:
            expected = identity({'plan': self.context['plan'], 'sharedPlan': self.context['sharedPlan'],
                                 'route': attempt['route'], 'engine': self.case.engine['identity']})
            self.assertEqual(attempt['identity'], expected)
        self.assertEqual((clip['counters']['previewLaunch'], clip['counters']['exportAttempt']), (1, 1))
        self.assertNotEqual(preview['productionBudget']['familyId'], final['productionBudget']['familyId'])

    def test_corrupt_declared_binding_refuses_admission_without_conservative_fallback(self) -> None:
        """An unavailable rate may fall back; a family-selected damaged artifact may not."""
        self.case.reserve('first')
        before = self.host.budget.record()
        pin = before['clips']['A']['sectionFamilies'][0]['reviewService']['envelope']
        Path(pin['path']).write_bytes(b'TEST damaged declared envelope')
        with self.assertRaises((ValueError, RuntimeError)):
            self.case.reserve('last')
        after = self.host.budget.record()
        self.assertEqual(after['clips']['A']['counters'], before['clips']['A']['counters'])
        self.assertEqual(after['clips']['A']['sectionFamilies'], before['clips']['A']['sectionFamilies'])

    def test_original_clock_is_checked_after_actual_binding_proof_read(self) -> None:
        """A real successful read finishing after expiry cannot admit another family child."""
        self.case.reserve('first')
        before = self.host.budget.record()
        original = binding.read_binding

        def late_read(session: object, context: dict, pin: dict) -> dict:
            """Advance only the existing fixture clock after the real proof completed."""
            result = original(session, context, pin)
            self.host.budget.elapsed = 20000
            return result

        with patch.object(binding, 'read_binding', side_effect=late_read):
            with self.assertRaises(BudgetRefused):
                self.case.reserve('last')
        after = self.host.budget.record()
        self.assertEqual(after['clips']['A']['counters'], before['clips']['A']['counters'])
        self.assertEqual(after['clips']['A']['sectionFamilies'], before['clips']['A']['sectionFamilies'])


class AuthoredBindingTests(unittest.TestCase):
    """Separately exercise actual authored chunk geometry without the admission fixture mock."""

    def test_actual_planned_binding_is_unmeasured_and_does_not_change_authored_bytes(self) -> None:
        """Freeze all actual scope geometry with no invented runtime or selected measured cell."""
        case = chunks.ChunkAdmissionTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        before = {path: path.read_bytes() for path in case.base.rglob('*') if path.is_file()}
        value = binding.planned_binding(case.project, case.context)
        self.assertEqual(value['plan'], case.context['plan'])
        self.assertEqual(value['sharedPlan'], case.context['sharedPlan'])
        self.assertEqual(value['envelope']['windows'], 60)
        self.assertEqual(len(value['envelope']['scopes']), 19)
        self.assertIsNone(value['envelope']['conditions'])
        self.assertTrue(all(row['selection'] is None for row in value['envelope']['envelopes']))
        self.assertEqual({path: path.read_bytes() for path in case.base.rglob('*') if path.is_file()}, before)


if __name__ == '__main__':
    unittest.main()
