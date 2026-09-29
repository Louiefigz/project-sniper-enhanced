"""Host contract (unit A1): typed handles, events, usage and capabilities; schema only, no client."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from _budget_fixture import host_turn, receipt
from studio.production import host_contract as contract
from studio.production.host_verdicts import HOST_RECORDS

TOKEN = '0123456789abcdef0123456789abcdef'


def event(kind: str, **values: object) -> dict:
    """A well-formed TEST host event of one type."""
    row = {'type': kind, 'taskId': 'critic-A', 'epoch': 1, 'token': TOKEN, 'handle': host_turn('critic'),
           'sequence': 3, 'receipts': [], 'failure': None, 'usage': None}
    return {**row, **values}


def usage(total: int | None, cached: int | None = None, output: int | None = None) -> dict:
    return {'inputTokens': total, 'outputTokens': output, 'cachedInputTokens': cached, 'reasoningTokens': None}


def supported_record() -> dict:
    """A synthetic host record in which every capability was observed to hold."""
    return {'host': 'codex', 'version': 'TEST', 'concurrency': 3,
            'capabilities': {name: {'verdict': 'supported', 'evidence': [f'/TEST/{name}.json'], 'caveat': None}
                             for name in contract.CAPABILITIES}}


class HandleTests(unittest.TestCase):
    """A handle names exactly one execution."""

    def test_process_and_host_handles(self) -> None:
        self.assertEqual(contract.process_handle(10, 10, 'Sun Sep 27 10:00:00 2026')['type'], 'process')
        self.assertEqual(contract.host_handle('claude-code', 'TEST-session', None)['turn'], None)
        for bad in ({'type': 'process', 'pid': 0, 'pgid': 1, 'started': 'x'},
                    {'type': 'process', 'pid': 1, 'pgid': 1, 'started': ''},
                    {'type': 'host', 'host': 'another-host', 'thread': 't', 'turn': None},
                    {'type': 'host', 'host': 'codex', 'thread': 'bad thread', 'turn': None},
                    {'type': 'host', 'host': 'codex', 'thread': 't', 'turn': None, 'command': 'x'}):
            with self.assertRaises(ValueError):
                contract.require_handle(bad)


class EventTests(unittest.TestCase):
    """The event schema is closed: each type carries exactly its own evidence."""

    def test_valid_events_parse_and_terminal_types_are_explicit(self) -> None:
        completed = contract.parse_event(event('completed', receipts=[receipt('findings')], usage=usage(10, 4)))
        self.assertTrue(completed.terminal)
        self.assertFalse(contract.parse_event(event('cancel-acknowledged')).terminal)
        self.assertTrue(contract.parse_event(event('interrupted')).terminal)
        self.assertEqual(contract.TERMINAL_EVENT_TYPES, ('completed', 'failed', 'interrupted'))

    def test_malformed_events_are_refused(self) -> None:
        cases = [event('completed', extra=1), event('finished'), event('accepted', epoch=0),
                 event('accepted', token='short'), event('accepted', handle={'type': 'process', 'pid': 3,
                                                                              'pgid': 3, 'started': 's'}),
                 event('accepted', receipts=[receipt('early')]), event('failed'),
                 event('completed', failure={'category': 'x', 'detail': ''}),
                 event('failed', failure={'category': 'Not A Slug', 'detail': ''}),
                 event('usage', usage=usage(5, 6)),
                 event('completed', receipts=[receipt('same'), receipt('same')])]
        for raw in cases:
            with self.assertRaises(ValueError, msg=raw):
                contract.parse_event(raw)


class UsageTests(unittest.TestCase):
    """Cumulative usage: unknown stays unknown, replays never lower a count, cached input is a subset."""

    def test_merge_takes_the_larger_known_value_per_field(self) -> None:
        merged = contract.merge_usage(usage(100, 40), usage(80, None, output=7))
        self.assertEqual(merged, usage(100, 40, output=7))
        self.assertEqual(contract.merge_usage(None, usage(None)), usage(None))
        with self.assertRaisesRegex(ValueError, 'cached input'):
            contract.merge_usage(usage(10), usage(None, 20))
        with self.assertRaises(ValueError):
            contract.merge_usage(None, {'inputTokens': 1})


class CapabilityTests(unittest.TestCase):
    """The §6 gate's observations per host build, and what they let Sniper claim."""

    def test_the_gate_records_parse_and_neither_host_supports_unattended_deadlines(self) -> None:
        for host, cleans in (('claude-code', True), ('codex', False)):
            report = contract.governance(contract.parse_capabilities(HOST_RECORDS[host]))
            self.assertEqual((report['mode'], report['interruptCleansUp'], report['endCleansUp']),
                             ('supervised', cleans, False))
            self.assertTrue({'absoluteAiExpiry', 'directorEnrollment', 'coordinatorDeathDelayedRestart'}
                            <= set(report['unsupported']))
            self.assertIn('knownHostConcurrency', report['unproven'])
        claude = contract.parse_capabilities(HOST_RECORDS['claude-code'])
        self.assertIn('API-key billing', claude.verdicts['subscriptionIdentityWithoutApiFallback']['caveat'])

    def test_without_an_observed_record_nothing_is_enforced(self) -> None:
        report = contract.governance(None)
        self.assertEqual((report['mode'], report['unproven']), ('record-only', list(contract.CAPABILITIES)))

    def test_only_a_fully_observed_host_is_unattended(self) -> None:
        record = supported_record()
        self.assertEqual(contract.governance(contract.parse_capabilities(record))['mode'], 'unattended')
        record['capabilities']['absoluteAiExpiry']['verdict'] = 'unsupported'
        self.assertEqual(contract.governance(contract.parse_capabilities(record))['mode'], 'supervised')
        record['capabilities']['interruptWithTerminalConfirmation']['verdict'] = 'unproven'
        self.assertEqual(contract.governance(contract.parse_capabilities(record))['mode'], 'record-only')

    def test_malformed_records_are_refused(self) -> None:
        cases = []
        for change in (lambda r: r['capabilities']['exactChildHandle'].update(evidence=[]),
                       lambda r: r['capabilities']['exactChildHandle'].update(verdict='PASS'),
                       lambda r: r['capabilities'].pop('directorEnrollment'),
                       lambda r: r.update(concurrency=None),
                       lambda r: r.update(host='another-host')):
            record = supported_record()
            change(record)
            cases.append(record)
        for record in cases:
            with self.assertRaises(ValueError):
                contract.parse_capabilities(record)

    def test_a_host_child_starts_from_a_clean_environment(self) -> None:
        clean = {name: 'x' for name in contract.CHILD_ENVIRONMENT}
        self.assertIsNone(contract.environment_problem(clean))
        problem = contract.environment_problem({**clean, 'ANTHROPIC_API_KEY': 'x', 'CLAUDE_CODE_SESSION_ID': 'y'})
        self.assertIn('ANTHROPIC_API_KEY', problem)
        self.assertIn('CLAUDE_CODE_SESSION_ID', problem)


class NoClientTests(unittest.TestCase):
    """The contract module imports no process, network or provider machinery."""

    def test_imports_are_schema_only(self) -> None:
        source = (Path(contract.__file__)).read_text()
        imported = {alias.name.split('.')[0] for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or '')])}
        self.assertEqual(imported, {'__future__', 'json', 'math', 're', 'dataclasses'})


if __name__ == '__main__':
    unittest.main()
