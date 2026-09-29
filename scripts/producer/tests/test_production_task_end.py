"""The one end rule (M-041): pure unit tests over task rows; no batch, pool or child process."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from itertools import product
from unittest.mock import patch

from studio.production import task_schema
from studio.production.task_end import (
    CAUSES, HOST_END_EVIDENCE, LOST, TERMINATED, end_cause, end_proof, late_cancel, observed_state, settle_end,
    settles_only,
)

PROCESS = {'type': 'process', 'pid': 4242, 'pgid': 4242, 'started': 'Mon Sep 28 20:00:00 2026'}
CLAUDE = {'type': 'host', 'host': 'claude-code', 'thread': 'thread-1', 'turn': 'turn-1'}
CODEX = {'type': 'host', 'host': 'codex', 'thread': 'thread-1', 'turn': 'turn-1'}
OTHER = {'type': 'unknown'}   # a handle type the rule has no row for: it fails closed (no branch is written for it)
LAUNCH_ERROR = 'spawn claude ENOENT'
RECEIPT = {'path': '/private/tmp/result.json', 'sha256': '0' * 64, 'bytes': 2}
ASSIGNMENT_ENDS = ('closure', 'host-ended', 'interrupt')
# (kind, handle, revoked, cause) -> (slot released, tool cleanup). The host rows P1 marked freed
# (claude-code host-ended, interrupt) are unresolved while HOST_END_EVIDENCE is empty (G9, N1).
TABLE = [
    *[(('check', PROCESS, False, cause), (True, 'unproven')) for cause in ('host-ended', 'interrupt', 'observed')],
    (('media', None, False, 'unlaunched'), (True, 'unproven')),
    (('author', None, False, 'unlaunched'), (True, 'unproven')),
    *[(('author', None, False, cause), (False, 'unproven')) for cause in ('host-ended', 'interrupt', 'observed')],
    (('review', PROCESS, False, 'observed'), (True, 'unproven')),
    *[(('review', PROCESS, False, cause), (False, 'unproven')) for cause in ('host-ended', 'interrupt')],
    *[(('author', CLAUDE, False, cause), (False, 'proved')) for cause in ('host-ended', 'interrupt')],
    (('author', CLAUDE, False, 'observed'), (False, 'unproven')),
    *[(('author', CODEX, False, cause), (False, 'unproven')) for cause in ('host-ended', 'interrupt', 'observed')],
    *[(('author', OTHER, False, cause), (False, 'unproven')) for cause in ('host-ended', 'interrupt', 'observed')],
    (('director', CLAUDE, False, 'closure'), (True, 'unproven')),
    (('director', CLAUDE, False, 'host-ended'), (True, 'proved')),
    (('director', CODEX, False, 'interrupt'), (True, 'unproven')),
    (('director', CLAUDE, False, 'observed'), (False, 'unproven')),
    (('director', PROCESS, False, 'observed'), (True, 'unproven')),
    (('director', PROCESS, True, 'observed'), (True, 'unproven')),
    (('director', CLAUDE, True, 'closure'), (False, 'unproven')),
    (('director', CLAUDE, True, 'host-ended'), (False, 'proved')),
]


def row(kind: str = 'author', handle: dict | None = None, **fields: object) -> dict:
    """A task row carrying the fields the end rule reads and writes (claimed until a handle is bound)."""
    task = {'id': 'task-1', 'kind': kind, 'handle': handle, 'revoked': False, 'cancelRequested': False,
            'state': 'running' if handle else 'claimed', 'receipts': [], 'unresolved': False, 'endConfirmed': False,
            'charged': True, 'reason': None, 'terminalElapsed': None}
    task.update(fields)
    return task


class EndRuleUnitTests(unittest.TestCase):
    """Every row of the rule, and the calls around it."""

    def test_every_table_row(self) -> None:
        """Each row gives its slot and cleanup results; a note explains every held slot and a director's end."""
        for (kind, handle, revoked, cause), (released, cleanup) in TABLE:
            with self.subTest(kind=kind, handle=handle and handle['type'], revoked=revoked, cause=cause):
                proof = end_proof(row(kind, handle, revoked=revoked), cause)
                self.assertEqual((proof.cause, proof.slot_released, proof.tool_cleanup), (cause, released, cleanup))
                assignment = kind == 'director' and not revoked and cause in ASSIGNMENT_ENDS
                self.assertEqual(proof.note is not None, not released or assignment)
                self.assertEqual(proof.event_fields(), {'endCause': cause, 'slotReleased': released,
                                                        'toolCleanup': cleanup})

    def test_label_never_changes_the_verdict(self) -> None:
        """A completed and a failed report end with the same cause and proof; a cancel request makes both interrupts."""
        for handle in (CLAUDE, CODEX, PROCESS):
            for cancel in (False, True):
                task = row('author', handle, cancelRequested=cancel)
                causes = {end_cause(task, report) for report in ('completed', 'failed')}
                self.assertEqual(causes, {'interrupt' if cancel else 'host-ended'})
                self.assertEqual(end_cause(task, 'interrupted'), 'interrupt')
        with self.assertRaisesRegex(ValueError, 'completed, failed or interrupted'):
            end_cause(row(), 'lost')

    def test_unknown_host_proves_nothing(self) -> None:
        """A host with no capability record proves neither the slot nor tool cleanup, for any cause."""
        with patch.dict(task_schema.HOST_RECORDS, clear=True):
            for handle, cause in product((CLAUDE, CODEX), ('host-ended', 'interrupt', 'observed')):
                proof = end_proof(row('author', handle), cause)
                self.assertEqual((proof.slot_released, proof.tool_cleanup), (False, 'unproven'))

    def test_settle_end_never_touches_charges(self) -> None:
        """Settling writes endConfirmed and unresolved only; the charge and the run's AI block stay."""
        for (kind, handle, revoked, cause), (released, _) in TABLE:
            task = row(kind, handle, revoked=revoked)
            record = {'production': {'ai': {'slots': 2, 'reservations': 4, 'charged': 1}, 'tasks': {'task-1': task}}}
            before, ai = copy.deepcopy(task), copy.deepcopy(record['production']['ai'])
            settle_end(task, cause)
            self.assertEqual(record['production']['ai'], ai)
            self.assertEqual(task, {**before, 'endConfirmed': True, 'unresolved': not released})

    def test_director_assignment_ends_only_by_closure_or_own_end(self) -> None:
        """Closure and the director's own end (host-ended or interrupt) release its assignment, with its own
        note; a host turn seen ended does not (X29); closure is for directors only."""
        director = row('director', CLAUDE)
        for cause in ASSIGNMENT_ENDS:
            proof = end_proof(director, cause)
            self.assertTrue(proof.slot_released)
            self.assertIn("director's batch assignment ended", proof.note)
        held = end_proof(director, 'observed')
        self.assertFalse(held.slot_released)
        self.assertIn('HOST_END_EVIDENCE', held.note)
        self.assertFalse(end_proof(row('director', CLAUDE, revoked=True), 'closure').slot_released)
        for kind in ('author', 'check', 'media'):
            with self.assertRaisesRegex(ValueError, 'director'):
                end_proof(row(kind), 'closure')

    def test_a_process_director_seen_gone_is_released_as_reconcile_releases_it(self) -> None:
        """G9 (b) for a process handle applies to a director too (X88 m5): the rule agrees with reconcile."""
        for revoked in (False, True):
            proof = end_proof(row('director', PROCESS, revoked=revoked), 'observed')
            self.assertEqual((proof.slot_released, proof.note), (True, None))
        self.assertEqual(observed_state(PROCESS, TERMINATED), TERMINATED)
        self.assertFalse(end_proof(row('director', PROCESS, revoked=True), 'host-ended').slot_released)

    def test_unlaunched_failure_needs_the_recorded_launch_error(self) -> None:
        """Only the launch tool's verbatim failure makes a claim unlaunched; a bare failure holds the slot.

        The launch error wins over a cancellation request (X88); an abandoned claim is refused."""
        task = row('author')
        self.assertEqual(end_cause(task, 'failed'), 'host-ended')
        self.assertFalse(end_proof(task, end_cause(task, 'failed')).slot_released)
        self.assertEqual(end_cause(task, 'failed', LAUNCH_ERROR), 'unlaunched')
        self.assertIsNone(settle_end(task, end_cause(task, 'failed', LAUNCH_ERROR)).note)
        self.assertIs(task['unresolved'], False)
        for state in ('cancel-requested', 'superseded'):
            self.assertEqual(end_cause(row(state=state, cancelRequested=True), 'failed', LAUNCH_ERROR), 'unlaunched')
        refused = [(row('author', CLAUDE), 'failed', LAUNCH_ERROR), (row(), 'completed', LAUNCH_ERROR),
                   (row('author', CLAUDE, state='cancel-requested', cancelRequested=True), 'failed', LAUNCH_ERROR),
                   (row(), 'interrupted', LAUNCH_ERROR), (row(state='abandoned'), 'failed', LAUNCH_ERROR),
                   (row(state='cancelled', cancelRequested=True), 'failed', LAUNCH_ERROR), (row(), 'failed', ''),
                   (row(), 'failed', '   '), (row(), 'failed', 'x' * 513), (row(), 'failed', '\u00e9' * 86),
                   (row(), 'failed', 7)]
        for task, report, error in refused:
            with self.subTest(state=task['state'], report=report, error=error), self.assertRaises(ValueError):
                end_cause(task, report, error)
        with self.assertRaisesRegex(ValueError, 'no execution acknowledged'):
            end_proof(row('author', PROCESS), 'unlaunched')

    def test_causes_and_the_empty_host_evidence_list(self) -> None:
        """The causes are fixed, and no host end event is evidence before M-102."""
        self.assertEqual(CAUSES, ('host-ended', 'interrupt', 'observed', 'unlaunched', 'closure'))
        self.assertEqual(HOST_END_EVIDENCE, {})
        with self.assertRaisesRegex(ValueError, 'end cause'):
            end_proof(row(), 'done')

    def test_observed_state_counts_a_terminal_state_only_with_evidence(self) -> None:
        """A process's observed end passes through; a host turn seen ended is lost (reconcile's rule)."""
        self.assertEqual(observed_state(PROCESS, TERMINATED), TERMINATED)
        for handle in (CLAUDE, CODEX, OTHER):
            self.assertEqual(observed_state(handle, TERMINATED), LOST)
        for status in ('alive', LOST, None):
            self.assertEqual(observed_state(CLAUDE, status), status)

    def test_late_cancel_keeps_the_result_as_history(self) -> None:
        """A live task ends cancelled with its receipts kept and its slot held; an ended one keeps its state."""
        task = row('author', CODEX, state='cancel-requested', cancelRequested=True)
        proof = late_cancel(task, ([RECEIPT], 'completed', 'interrupt'), 12.0)
        self.assertEqual((proof.cause, proof.slot_released), ('interrupt', False))
        self.assertEqual((task['state'], task['receipts'], task['terminalElapsed']), ('cancelled', [RECEIPT], 12.0))
        self.assertTrue(task['unresolved'] and task['endConfirmed'])
        self.assertIn('reported completed', task['reason'])
        lost = row('author', PROCESS, state='abandoned', cancelRequested=True, reason='host lost', terminalElapsed=5.0)
        late_cancel(lost, ([], 'launch-failed', 'interrupt'), 13.0)
        self.assertEqual((lost['state'], lost['receipts'], lost['terminalElapsed']), ('abandoned', [], 5.0))
        self.assertTrue(lost['reason'].startswith('host lost; cancellation was requested'))
        bare = row('author', PROCESS, state='abandoned', cancelRequested=True, terminalElapsed=5.0)
        late_cancel(bare, ([], 'failed', 'interrupt'), 13.0)
        self.assertTrue(bare['reason'].startswith('abandoned; cancellation was requested'))

    def test_late_cancel_of_an_unlaunched_claim_releases_its_slot(self) -> None:
        """A cancel-requested claim whose launch call failed ends cancelled with its slot released (X88)."""
        task = row('author', state='cancel-requested', cancelRequested=True)
        proof = late_cancel(task, ([], 'launch-failed', end_cause(task, 'failed', LAUNCH_ERROR)), 7.0)
        self.assertEqual((proof.cause, proof.slot_released, proof.tool_cleanup), ('unlaunched', True, 'unproven'))
        self.assertEqual((task['state'], task['unresolved'], task['endConfirmed']), ('cancelled', False, True))
        self.assertIn('launch call then failed (launch-failed); nothing ran', task['reason'])
        for task, cause in ((row(), 'interrupt'), (row(state='cancel-requested', cancelRequested=True), 'host-ended')):
            with self.subTest(cause=cause), self.assertRaisesRegex(ValueError, 'cancellation was requested'):
                late_cancel(task, ([], 'completed', cause), 1.0)


class CancelWinsTests(unittest.TestCase):
    """The pure part of cancellation precedence (P1 A2); M-042 adds the flow tests."""

    def test_settles_only_predicate(self) -> None:
        """History only: cancel-requested or cancelled after a request, and reportable or receipted revoked work."""
        cases = [(row(), True, False), (row(state='cancel-requested', cancelRequested=True), True, True),
                 (row(state='cancelled', cancelRequested=True), False, True), (row(state='completed'), False, False),
                 (row(state='superseded'), True, True), (row(state='superseded'), False, False),
                 (row(state='abandoned', receipts=[RECEIPT]), False, True), (row(state='abandoned'), False, False),
                 (row(state='cancelled'), False, False)]
        for task, may_report, expected in cases:
            with self.subTest(state=task['state'], cancel=task['cancelRequested'], may_report=may_report):
                self.assertIs(settles_only(task, may_report), expected)


if __name__ == '__main__':
    unittest.main()
