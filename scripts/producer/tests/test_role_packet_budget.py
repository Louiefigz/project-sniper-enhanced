"""Plan-critic time budgets and mechanical receipts (P2-11): role_packet_budget and the packets that carry them.

Records are TEST batch records built in memory (``_budget_fixture``); built projects, early reports and plans are
TEST files under the fixture's private root. Nothing here reads a live authority, renders or reviews anything.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from pathlib import Path

import context as entry
import role_packet_budget as budget
from _budget_fixture import approval, source_sha
from _role_packet_fixture import RolePacketFixture, sha
from role_packet_budget import BudgetRequest, receipt_rows, review_budget
from role_packet_files import ArtifactError
from role_packet_native import plan_hash
from role_packets import RoleRequest, resolve_role_packet
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record

REPO = entry.REPO


def record() -> dict:
    """A TEST batch whose clip A has its preparation deadline at 1500 s (minute 25 of its own clock)."""
    spec = BatchSpec('batch-budget', ('A',), (source_sha(),), 1, approvals={'A': approval('A')})
    return new_batch_record(spec, start_anchor())


def plan_budget(resolved: float | None, repair: bool = False) -> dict:
    """The plan-critic budget of clip A resolved at ``resolved`` (None: outside a batch)."""
    return review_budget(BudgetRequest('plan-critic', None if resolved is None else record(), 'A', resolved, repair))


class BudgetTests(unittest.TestCase):
    """hardBy = min(resolved + hardSeconds, preparation - 60); no-repair-window at or before resolution."""

    def test_budget_capped_by_preparation_cutoff(self) -> None:
        """600 s after resolution until the cutoff 1440 s binds; a repair gets 360 s and the early checkpoint 240 s."""
        self.assertEqual(plan_budget(100.0), {'kind': 'plan-critic', 'status': 'bounded', 'resolvedElapsed': 100.0,
                                             'earlyBy': 520.0, 'hardBy': 700.0})
        self.assertEqual((plan_budget(1000.0)['earlyBy'], plan_budget(1000.0)['hardBy']), (1420.0, 1440.0))
        self.assertEqual((plan_budget(1100.0)['earlyBy'], plan_budget(1100.0)['hardBy']), (1440.0, 1440.0))
        repair = plan_budget(1000.0, repair=True)
        self.assertEqual((repair['kind'], repair['earlyBy'], repair['hardBy']), ('plan-critic-repair', 1240.0, 1360.0))

    def test_no_repair_window(self) -> None:
        """At or past the cutoff the critic still gets a budget, marked as leaving no repair window."""
        for resolved, status in ((1439.999, 'bounded'), (1440.0, 'no-repair-window'), (1500.0, 'no-repair-window')):
            with self.subTest(resolved=resolved):
                found = plan_budget(resolved)
                self.assertEqual((found['status'], found['hardBy']), (status, 1440.0))

    def test_unbatched_packet(self) -> None:
        """Outside a batch there is no clock and no deadline; an unbudgeted role is refused by name."""
        self.assertEqual(plan_budget(None), {'kind': 'plan-critic', 'status': 'unbatched', 'resolvedElapsed': None,
                                            'earlyBy': None, 'hardBy': None})
        with self.assertRaisesRegex(ArtifactError, 'no review budget is defined for motion-critic'):
            review_budget(BudgetRequest('motion-critic', None, None, None, False))

    def test_packet_terms_and_the_authority_rule(self) -> None:
        """The packet carries terms only; the rule the authority runs at resolution gives review_budget's deadlines."""
        self.assertEqual({key: value for key, value in budget.budget_terms(True).items() if key != 'deadlines'},
                         {'kind': 'plan-critic-repair', 'earlySeconds': 240, 'hardSeconds': 360,
                          'repairStartMarginSeconds': 60})
        found = budget.resolution_budget('A', budget.budget_terms(False))(record(), 1000.0)
        self.assertEqual(found, plan_budget(1000.0))
        self.assertEqual(budget.resolution_budget('A', budget.budget_terms(True))(record(), 1000.0)['hardBy'], 1360.0)


class ReceiptFixture(RolePacketFixture):
    """A TEST plan, a project built from it and that project's passing early report."""

    def built(self, name: str = 'native-v1', status: str = 'passed', change: dict | None = None) -> tuple[Path, Path]:
        """(built project's PROJECT-MANIFEST.json, its early report); the build adds generated bindings and `draft`."""
        self.planned = self.plan() if not hasattr(self, 'planned') else self.planned
        value = {**json.loads(self.planned.read_text()), 'draft': {'TEST': 'draft authority'}, **(change or {})}
        project = self.write(f'clip/{name}/SHORT-PROJECT.json', value)
        manifest = self.write(f'clip/{name}/PROJECT-MANIFEST.json', {'schemaVersion': 1,
                              'scope': 'native-short-review-project', 'structuralStrategyChecks': status,
                              'files': [{'file': 'SHORT-PROJECT.json', 'sha256': sha(project)}]})
        report = self.early(project.parent, name)
        return manifest, report

    def early(self, directory: Path, name: str, **fields: object) -> Path:
        """A TEST early report of the built project ``directory`` (passing unless ``fields`` say otherwise)."""
        return self.write(f'evidence/{name}-early/early-check-report.json', {'schemaVersion': 2,
                          'scope': 'native-short-early-defect-report', 'status': 'no-early-defects-found',
                          'project': str(directory), **fields})

    def wanted(self) -> str:
        """The reviewed plan's hash."""
        return plan_hash(json.loads(self.planned.read_text()))


class ReceiptTests(ReceiptFixture):
    """Exactly one passing early report and one build receipt, of one project built from this very plan."""

    def test_receipt_for_other_plan_refused(self) -> None:
        """Another plan's build, another project's early report, a changed project file or one receipt is refused."""
        manifest, report = self.built()
        rows = receipt_rows((str(report), str(manifest)), self.wanted())
        self.assertEqual({row['kind']: row['planHash'] for row in rows},
                         {'early-report': self.wanted(), 'build': self.wanted()})  # `draft` excluded, as TS does
        other_manifest, other_report = self.built('native-v2', change={'canvas': {'frameRate': '30/1', 'totalFrames': 91}})
        with self.assertRaisesRegex(ArtifactError, rf'receipt {other_manifest} is for plan [0-9a-f]{{64}}, not {self.wanted()}'):
            receipt_rows((str(report), str(other_manifest)), self.wanted())
        twin_manifest, twin_report = self.built('native-v3')
        with self.assertRaisesRegex(ArtifactError, f'receipt {twin_report} is for project .*native-v3, not .*native-v1'):
            receipt_rows((str(twin_report), str(manifest)), self.wanted())
        with self.assertRaisesRegex(ArtifactError, 'exactly one early report and one build receipt'):
            receipt_rows((str(report),), self.wanted())
        with self.assertRaisesRegex(ArtifactError, 'exactly one early report and one build receipt'):
            receipt_rows((str(report), str(twin_report)), self.wanted())
        (manifest.parent / 'SHORT-PROJECT.json').write_text('{"changed": true}')
        with self.assertRaisesRegex(ArtifactError, 'is not a built native Short project whose manifest binds'):
            receipt_rows((str(report), str(manifest)), self.wanted())
        self.assertTrue(other_report.exists() and twin_manifest.exists())

    def test_failed_receipt_refused(self) -> None:
        """A report with defects or incomplete, a failed build, schema 1, a relative project or another file."""
        manifest, report = self.built()
        for fields, message in (({'status': 'defects-found'}, r'did not pass \(defects-found\)'),
                                ({'status': 'incomplete'}, r'did not pass \(incomplete\)'),
                                ({'schemaVersion': 1}, 'early report schema 1, not 2'),
                                ({'project': 'clip/native-v1'}, 'names no absolute project')):
            with self.subTest(fields=fields), self.assertRaisesRegex(ArtifactError, message):
                receipt_rows((str(self.early(manifest.parent, 'bad', **fields)), str(manifest)), self.wanted())
        failed, _report = self.built('native-v4', status='failed')
        with self.assertRaisesRegex(ArtifactError, r'did not pass \(failed\)'):
            receipt_rows((str(report), str(failed)), self.wanted())
        with self.assertRaisesRegex(ArtifactError, "neither an early report nor a built project's"):
            receipt_rows((str(report), str(self.planned)), self.wanted())


class PacketReceiptTests(ReceiptFixture):
    """Packets carry the budget and receipts; receipt checks and the feature appear only when receipts are bound."""

    def test_packet_carries_budget_and_receipts(self) -> None:
        """A plan-critic packet binds both receipts as frozen `bound` artifacts; a repair packet has the repair budget."""
        manifest, report = self.built()
        packet = resolve_role_packet(RoleRequest(role='plan-critic', plan=str(self.planned),
                                                 receipts=(str(report), str(manifest))), REPO)['packet']
        self.assertEqual([row['kind'] for row in packet['mechanicalReceipts']], ['early-report', 'build'])
        reading = {row['key']: row['read'] for row in packet['artifacts']}
        self.assertEqual((reading['receipt:early-report'], reading['receipt:build']), ('bound', 'bound'))
        self.assertEqual((packet['budget']['kind'], packet['budget']['hardSeconds']), ('plan-critic', 600))
        prior = self.write('reviews/PREBUILD-REVIEW-v1.json', {'TEST': 'earlier plan review'})
        repair = resolve_role_packet(RoleRequest(role='plan-critic', plan=str(self.planned), prior_reviews=str(prior)),
                                     REPO)['packet']
        self.assertEqual((repair['budget']['kind'], repair['mechanicalReceipts']), ('plan-critic-repair', None))
        self.assertIn(('prior-plan-review', 'history'), [(row['key'], row['read']) for row in repair['artifacts']])

    def test_receipt_checks_added_only_when_bound(self) -> None:
        """PC-21 and the feature only with receipts; OW-21 for an owner with receipts; no receipts for other critics."""
        manifest, report = self.built()
        bare = resolve_role_packet(RoleRequest(role='plan-critic', plan=str(self.planned)), REPO)['packet']
        self.assertNotIn('PC-21', [row['id'] for row in bare['checks']])
        self.assertIs(bare['features']['mechanical-receipts'], False)
        self.assertIn('timeBudget', bare['obligations'])
        bound = resolve_role_packet(RoleRequest(role='plan-critic', plan=str(self.planned),
                                                receipts=(str(report), str(manifest))), REPO)['packet']
        self.assertIn('PC-21', [row['id'] for row in bound['checks']])
        self.assertIs(bound['features']['mechanical-receipts'], True)
        owner = resolve_role_packet(RoleRequest(role='clip-owner', plan=str(self.planned),
                                                receipts=(str(report), str(manifest))), REPO)['packet']
        self.assertIn('OW-21', [row['id'] for row in owner['checks']])
        self.assertNotIn('budget', owner)
        with self.assertRaisesRegex(ArtifactError, '--receipt binds a plan'):
            resolve_role_packet(RoleRequest(role='clip-owner', project=str(self.root / 'clip'),
                                            receipts=(str(report), str(manifest))), REPO)


if __name__ == '__main__':
    unittest.main()
