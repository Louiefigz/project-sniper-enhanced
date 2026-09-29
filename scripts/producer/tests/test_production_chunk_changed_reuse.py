"""Changed B2 retains only proved B1/B3 original judgments; fictional media is not qualification."""
from __future__ import annotations

import copy
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _production_chunk_changed_fixture import ChangedChunkFixture
from studio.production import api
from studio.production.section_chunk_reuse import local_compatibility, read_retained_chunk, retained_chunk_scopes
from studio.production.task_schema import holds_slot


class ChangedChunkReuseTests(unittest.TestCase):
    """Exercise real repair authority, media seals and old recorded review claim provenance."""

    def setUp(self) -> None:
        """Build one immutable original author generation with current independent progress."""
        self.fixture = ChangedChunkFixture(self)
        self.host = self.fixture.host

    def carried(self) -> list[dict]:
        """Ask the read-only proof helper without changing task or accounting state."""
        return retained_chunk_scopes(self.host.budget.record(), self.host.request,
                                     self.host.context['assignments'][0])

    def test_changed_middle_chunk_preserves_original_outer_judgments_only(self) -> None:
        """B1/B3 carry exact old provenance; B2 and both contextual seams need current review."""
        self.fixture.record_original()
        old = self.fixture.review.task()
        self.fixture.repair()
        before = self.host.budget.record()
        values = self.carried()
        self.assertEqual([row['frameRange'] for row in values], [[0, 60], [120, 180]])
        self.assertEqual({row['scopeKind'] for row in values}, {'chunk'})
        self.assertEqual({row['originalTaskId'] for row in values}, {old['id']})
        self.assertTrue(all(row['originalReceipt'] == old['sectionProgress'][row['scopeId']] for row in values))
        self.assertTrue(all(read_retained_chunk(row)['scopeId'] == row['scopeId'] for row in values))
        changed = copy.deepcopy(values[0])
        changed['currentScope']['frameRange'][1] += 1
        with self.assertRaisesRegex(ValueError, 'proof or current dependencies changed'):
            read_retained_chunk(changed)
        self.assertEqual(before, self.host.budget.record())
        self.assertEqual(before['clips']['A']['counters']['author'], 1)
        self.assertEqual(before['clips']['A']['counters']['repairCycle'], 1)
        self.assertEqual(before['production']['tasks'][old['id']]['state'], 'superseded')

    def test_original_receipt_corruption_is_refused(self) -> None:
        """An old pass never survives mutation of the original reviewed bytes."""
        self.fixture.record_original()
        self.fixture.repair()
        pin = self.fixture.review.task()['sectionProgress'][self.fixture.review.scopes()[0]['id']]
        Path(pin['path']).write_text('TEST corrupted recorded judgment')
        with self.assertRaises((ValueError, RuntimeError)):
            self.carried()

    def test_earlier_ready_chunk_carries_while_later_donor_awaits_current_reseal(self) -> None:
        """An old B3 donor is pending, but it cannot block a proved current B1 judgment."""
        self.fixture.record_original()
        self.fixture.repair((0,))
        self.assertEqual([row['frameRange'] for row in self.carried()], [[0, 60]])
        from studio.production.section_chunk_plan import ready_chunk_scopes
        from studio.production.section_chunk_presentation import package_ready_scopes
        from studio.production.sections import encoded_spec
        from studio.native_segments.review_package import ensure_package
        spec = encoded_spec(self.host.request, self.host.context['assignments'][0], self.host.budget.record())
        ready = ready_chunk_scopes(spec.section_binding, self.host.request)
        self.assertEqual([scope['frameRange'] for scope in ready], [[0, 60]])
        with patch('studio.native_segments.review_package.ensure_package', wraps=ensure_package) as package:
            package_ready_scopes(SimpleNamespace(request=self.host.request))
        self.assertEqual(package.call_args_list, [])
        api.supersede_task(self.host.budget.root, 'section-test', self.fixture.review.ref.task_id,
                           'TEST require fresh B1 presentation after withdrawal')
        with patch('studio.native_segments.review_package.ensure_package', wraps=ensure_package) as package:
            package_ready_scopes(SimpleNamespace(request=self.host.request))
        self.assertEqual([call.args[1] for call in package.call_args_list], [ready[0]['id']])
        self.assertFalse((Path(self.host.request['output']) / 'segment-picture-2-stage.json').exists())
        self.assertIn('segment-picture-2', self.host.request['revision']['windowDonors'])
        audio = Path(self.host.request['output']) / 'segment-picture-0-TEST.wav'
        audio.write_bytes(b'TEST corrupt present media while a later chunk is pending')
        with self.assertRaises((ValueError, RuntimeError)):
            ready_chunk_scopes(spec.section_binding, self.host.request)

    def test_new_author_cannot_be_original_reviewer(self) -> None:
        """Carry requires independence against both authored generations, not merely the old author."""
        self.fixture.record_original()
        self.fixture.repair()
        record = copy.deepcopy(self.host.budget.record())
        author = record['production']['tasks'][self.host.context['assignments'][0]['authorTaskId']]
        reviewer = record['production']['tasks'][self.fixture.review.ref.task_id]
        author['handle'] = copy.deepcopy(reviewer['handle'])
        with self.assertRaisesRegex(ValueError, 'original or current author'):
            retained_chunk_scopes(record, self.host.request, self.host.context['assignments'][0])

    def test_partial_progress_retains_provenance_but_never_revives_callback_or_releases_slot(self) -> None:
        """A still-live old reviewer remains accounted for after its author is replaced."""
        self.fixture.record_original(complete=False)
        self.fixture.repair()
        before = self.host.budget.record()
        old = before['production']['tasks'][self.fixture.review.ref.task_id]
        self.assertTrue(holds_slot(old))
        values = self.carried()
        self.assertEqual([row['frameRange'] for row in values], [[0, 60], [120, 180]])
        with self.assertRaises((ValueError, RuntimeError)):
            self.fixture.review.record(values[0]['originalReceipt'])
        self.assertEqual(before['production']['tasks'], self.host.budget.record()['production']['tasks'])
        self.assertEqual(before['clips']['A']['counters'], self.host.budget.record()['clips']['A']['counters'])

    def test_independently_revoked_old_review_cannot_be_carried(self) -> None:
        """An unrelated manual revocation is not converted to author-repair provenance."""
        self.fixture.record_original()
        api.supersede_task(self.host.budget.root, 'section-test', self.fixture.review.ref.task_id,
                           'TEST judgment independently withdrawn')
        self.fixture.repair()
        self.assertEqual(self.carried(), [])

    def test_explicit_withdrawal_after_repair_remains_durable_and_idempotent(self) -> None:
        """Already-revoked old tasks can withdraw retained judgments without altering held resources."""
        self.fixture.record_original(complete=False)
        self.fixture.repair()
        self.assertEqual(len(self.carried()), 2)
        before = self.host.budget.record()
        task_id = self.fixture.review.ref.task_id
        result = api.supersede_task(self.host.budget.root, 'section-test', task_id, 'TEST withdraw original judgment')
        self.assertEqual(result['superseded'], [task_id])
        self.assertTrue(result['committed'])
        after = self.host.budget.record()
        self.assertTrue(holds_slot(after['production']['tasks'][task_id]))
        self.assertEqual(before['clips']['A']['counters'], after['clips']['A']['counters'])
        self.assertEqual(self.carried(), [])
        replay = api.supersede_task(self.host.budget.root, 'section-test', task_id, 'TEST withdraw original judgment')
        self.assertFalse(replay['committed'])
        self.assertEqual(after['production']['tasks'], self.host.budget.record()['production']['tasks'])

    def test_current_pcm_corruption_and_unknown_shared_changes_are_refused(self) -> None:
        """Identical picture alone cannot approve changed audio or unsupported global dependencies."""
        self.fixture.record_original()
        self.fixture.repair()
        project = self.host.budget.base / 'unknown-shared-project'
        shutil.copytree(self.host.fixture.project, project)
        (project / 'unknown-global-policy.txt').write_text('TEST changed shared input')
        current = copy.deepcopy(self.host.request)
        self.fixture.project_pins(current, project)
        with self.assertRaises((ValueError, RuntimeError)):
            local_compatibility(self.fixture.original, current, [0, 60])
        audio = Path(self.host.request['output']) / 'segment-picture-0-TEST.wav'
        audio.write_bytes(b'TEST changed current PCM')
        with self.assertRaises((ValueError, RuntimeError)):
            self.carried()

    def test_authored_transition_decision_is_part_of_local_compatibility(self) -> None:
        """Same media geometry cannot carry a judgment across changed local transition intent."""
        original = copy.deepcopy(self.host.request)
        project = self.host.budget.base / 'new-transition-decision'
        shutil.copytree(self.host.fixture.project, project)
        file = project / 'LONG-CHUNKS.json'
        value = json.loads(file.read_text())
        value['transitions'][0]['version'] += 1
        value['transitions'][0]['continuity']['imagery'] = 'TEST different current transition judgment'
        file.write_text(json.dumps(value))
        current = copy.deepcopy(original)
        self.fixture.project_pins(current, project)
        self.assertIsNone(local_compatibility(original, current, [0, 60]))
        self.assertIsNotNone(local_compatibility(original, current, [120, 180]))


class UnclaimedChunkReuseTests(unittest.TestCase):
    """An enqueued reviewer has no recorded historical judgment to transfer."""

    def test_unclaimed_original_reviewer_is_pending_evidence_not_an_invalid_claim(self) -> None:
        """Absence of original progress returns no carry without masking any present corrupt proof."""
        fixture = ChangedChunkFixture(self, claim_review=False)
        fixture.repair((0,))
        host = fixture.host
        self.assertEqual(retained_chunk_scopes(host.budget.record(), host.request, host.context['assignments'][0]), [])


if __name__ == '__main__':
    unittest.main()
