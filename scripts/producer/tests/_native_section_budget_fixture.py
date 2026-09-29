"""Private real authority records and controlled clocks for section-budget tests."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import tempfile
from pathlib import Path
from unittest import mock

from studio import native_budget_clock as clock
from studio.native_budget_batches import create_batch
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_store import read_batch
from studio.production.outputs import OutputAuthorization, _new_output
from studio.production.task_schema import authorization_identity

SUPERVISOR = {'pid': 7001, 'pgid': 7001, 'started': 'TEST supervisor'}


class SectionBudgetFixture:
    """Never read or mutate the account's live production-budget root."""

    def __init__(self, test: object) -> None:
        """Create one authorized Long with a reserved export and fake original clock."""
        self.base = Path(test.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.base / 'budgets'
        self.elapsed = 0.0
        test.enterContext(mock.patch.object(clock, 'boot_id', return_value='test-boot'))
        test.enterContext(mock.patch.object(clock, 'continuous_now', side_effect=lambda: 1000 + self.elapsed))
        test.enterContext(mock.patch.object(clock.time, 'time', side_effect=lambda: 1800000000 + self.elapsed))
        test.enterContext(mock.patch('studio.native_budget_sections.own_identity', return_value=SUPERVISOR))
        test.enterContext(mock.patch('studio.native_budget_sections._process_table', return_value={
            7001: (1, 7001, 'TEST supervisor')}))
        record = new_batch_record(BatchSpec('section-test', ('A',), (), 1), clock.start_anchor())
        record['clips']['A'] = _new_output(record, OutputAuthorization('A', 'long', 'TEST', 'TEST',
                                                                      output_seconds=60), 0)
        record['production']['authorization']['identity'] = authorization_identity(record)
        self.request = self.make_request()
        record['clips']['A']['attempts'] = [self.attempt()]
        record['clips']['A']['counters']['exportAttempt'] = 1
        create_batch(self.root, record)

    def make_request(self) -> dict:
        """The same two-window picture plan for every resumed attempt."""
        windows = [{'index': i, 'id': f'section-{i}', 'inputIdentity': str(i) * 64} for i in range(2)]
        return {'project': str(self.base / 'project'), 'output': str(self.base / 'output'), 'pins': {},
                'revision': {'identity': 'c' * 64, 'renderWindows': windows}, 'audioProfile': 'TEST',
                'productionBudget': {'authority': str(self.root), 'batchId': 'section-test', 'clipId': 'A',
                                     'attemptId': 'a' * 32, 'allocation': clock.allocation(clock.start_anchor(), 9000, 45)}}

    def attempt(self) -> dict:
        """An ordinary reserved export row, with the original bounded allocation."""
        return {'id': 'a' * 32, 'route': 'final', 'project': self.request['project'],
                'output': self.request['output'], 'identity': 'b' * 64, 'admittedElapsed': 0,
                'outputSeconds': 60.0, 'grantedSeconds': 9000.0, 'supervisor': SUPERVISOR,
                'status': 'running', 'resultStatus': None, 'failure': None, 'completedElapsed': None,
                'stages': [], 'nested': {}, 'transientRetryOf': None}

    def record(self) -> dict:
        """Read through the production store's lock and closed validator."""
        return read_batch(self.root, 'section-test')

    def raw(self, record: dict) -> None:
        """Only corruption/compatibility tests write raw TEST authority bytes."""
        (self.root / 'batches/section-test/authority.json').write_text(json.dumps(record))
