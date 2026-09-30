"""The event trail's terminal reserve holds every settling line a batch can still owe (X192, X104's "a close always
fits", as a check in code rather than a comment).

Each class below is built at its largest shape (every field at its validator's bound, encoded as
``native_budget_store.canonical`` writes it) and counted at its bound from the record's own limits. Their sum must
fit ``TERMINAL_RESERVE_BYTES``: past ``MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES`` only these lines are written, so a
batch at a full trail can still cancel a stalled Short, settle every task, record every abandoned launch and close.
Pure arithmetic on constants; nothing is written.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import sys
import unittest

from studio.native_budget_schema_data import BOUNDS
from studio.native_budget_store import MAX_EVENT_BYTES, TERMINAL_RESERVE_BYTES, canonical
from studio.production.queue_authority import CHECKPOINT_EVENT_BYTES
from studio.production.queue_clock import SETTLED
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, MAX_WORKERS
from studio.production.task_schema import MAX_TASK_OWNERS

BIG = sys.float_info.max                 # the longest float spelling
TEXT = 'x' * 512                          # clip_text and the validators bound a text at 512 encoded bytes
TASK = 'T' * 64                           # task_schema.TASK_ID
CLIP = 'C' * 64                           # native_budget_store.CLIP_ID
ATTEMPT = 'a' * 32                        # native_budget_schema._attempt_id
PROCESS = {'type': 'process', 'pid': 2 ** 31, 'pgid': 2 ** 31, 'started': 's' * 64}   # host_contract.valid_handle
CLIPS, TASKS, ATTEMPTS = BOUNDS['clips'], BOUNDS['tasks'], BOUNDS['clips'] * BOUNDS['attempts']


def size(value: dict) -> int:
    """Bytes of one trail line."""
    return len(canonical(value))


def settlement() -> dict:
    """One task's largest ``capacitySettled``: its own Short, every owner row of the clock removed."""
    return {CLIP: {'elapsed': BIG, 'excludedSeconds': BIG, 'removedWorkers': ['f' * 16] * MAX_WORKERS}}


def budget() -> dict:
    """Each settling class's worst case in bytes."""
    stall = {'event': 'capacity-stall-decided', 'clipId': CLIP, 'kind': 'cancel', 'reason': TEXT, 'state': 'cancelled',
             'frozen': []}
    settle = {'event': 'task-completed', 'epoch': 2 ** 31, 'taskId': TASK, 'state': 'superseded',
              'failure': {'category': 'c' * 64, 'detail': TEXT}, 'owners': [PROCESS] * MAX_TASK_OWNERS,
              SETTLED: settlement()}
    change = {'taskId': TASK, 'from': 'cancel-requested', 'to': 'superseded', 'unresolved': True, 'reason': TEXT,
              SETTLED: settlement()}
    close = {'event': 'batch-closed', 'unsettled': [TASK] * TASKS, 'runningAttempts': [ATTEMPT] * ATTEMPTS,
             'revoked': [TASK] * TASKS, 'directorEnd': {'taskId': TASK, 'cause': 'closure', 'detail': TEXT}}
    return {
        'capacity-checkpoint': MAX_CHECKPOINTS * CLIPS * CHECKPOINT_EVENT_BYTES,
        # one per Short (decide refuses a second); a task is frozen by at most one cancel
        'capacity-stall-decided': CLIPS * size(stall) + TASKS * len(canonical([TASK])),
        # an observation that marked dead launches abandoned: at most one line per attempt
        'observed (abandoned)': ATTEMPTS * size({'event': 'observed', 'elapsed': BIG, 'abandoned': [ATTEMPT]}),
        # each task settles once, by its watchdog (task-*) or by reconcile (a tasks-reconciled change), and is
        # counted here for both, each carrying the largest capacitySettled
        'task settlement (task-*)': TASKS * size(settle),
        'task settlement (tasks-reconciled)': TASKS * len(canonical(change)) + size({'event': 'tasks-reconciled',
                                                                                     'changes': []}),
        'batch-closed': size(close),
    }


class ReserveBudgetTests(unittest.TestCase):
    """The worst case of every settling class fits the reserve, and new work keeps its own room."""

    def test_every_settling_class_fits_the_terminal_reserve(self) -> None:
        """The sum of the classes' worst cases is within TERMINAL_RESERVE_BYTES."""
        rows = budget()
        total = sum(rows.values())
        self.assertLessEqual(total, TERMINAL_RESERVE_BYTES, rows)

    def test_new_work_keeps_fifteen_mebibytes(self) -> None:
        """Raising the reserve raised the trail bound with it: new work still stops at 15 MiB."""
        self.assertEqual(MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES, 15 * 1024 ** 2)


if __name__ == '__main__':
    unittest.main()
