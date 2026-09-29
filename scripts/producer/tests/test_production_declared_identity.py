"""Declared handles, identity keys and end observations (P3b-1, M-088, decision D-E)."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from studio.production import declared_identity as di
from studio.production import host_contract

SESSION_ID = 's-0123456789abcdef'
LAUNCH = '0123456789abcdef0123456789abcdef'
CLAUDE_AGENT = 'a0f1e2d3c4b5a6978'     # the shape of a Claude Code agentId
CODEX_AGENT = '/root/author_q1'
PROCESS = {'pid': 4242, 'pgid': 4242, 'started': 'Mon Sep 28 21:16:06 2026'}
LONGEST_PATH = ('/' + 'a' * 63) * 3 + '/' + 'b' * 7          # 200 bytes
TOO_LONG_PATH = LONGEST_PATH + 'c'                              # 201 bytes


def director(host: str = 'claude-code') -> dict:
    """A valid director handle with a known host thread and 4 slots."""
    return di.director_handle(host, SESSION_ID, 'thread-1', 4)


def subagent(agent: str = CODEX_AGENT, host: str = 'codex') -> dict:
    """A valid subagent handle of ``director(host)``."""
    return di.subagent_handle(director(host), agent, LAUNCH)


def host_handle(turn: str | None = 'turn-9') -> dict:
    """A historical host handle as older records hold it."""
    return {'type': 'host', 'host': 'codex', 'thread': 'thread-1', 'turn': turn}


def end(tool: str, status: str) -> str:
    """An --end-observation text."""
    return '{"tool": "%s", "status": "%s"}' % (tool, status)


class DeclaredIdentityTests(unittest.TestCase):
    """P3b-1's twelve tests and M-088's two hostProcess tests (X40, D-E)."""

    def assertInvalid(self, values: list) -> None:
        """Each value is not a valid declared handle."""
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(di.valid_declared(value))

    def test_director_handle_has_slots_and_no_agent(self) -> None:
        """A director names host, session, optional thread and 2..16 slots, and no agent or launch."""
        handle = director('codex')
        self.assertEqual(handle, {'type': 'declared', 'host': 'codex', 'session': SESSION_ID, 'agent': None,
                                  'launch': None, 'hostThread': 'thread-1', 'slots': 4, 'hostProcess': None})
        self.assertTrue(di.valid_declared(di.director_handle('claude-code', SESSION_ID, None, 2)))
        self.assertTrue(di.valid_declared(di.director_handle('claude-code', SESSION_ID, None, 16)))
        bad = [('codex', SESSION_ID, None, 1), ('codex', SESSION_ID, None, 17), ('codex', SESSION_ID, None, True),
               ('codex', SESSION_ID, None, 2.0), ('gemini', SESSION_ID, None, 4), ('codex', 'x', None, 4),
               ('codex', SESSION_ID, 'bad thread', 4), ('codex', SESSION_ID, '', 4), ('codex', SESSION_ID, True, 4)]
        for args in bad:
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, '^A declared director handle names'):
                di.director_handle(*args)
        missing = dict(handle)
        del missing['hostProcess']
        self.assertInvalid([{**handle, 'launch': LAUNCH}, {**handle, 'extra': 1}, missing,
                            {**handle, 'type': 'host'}, {**handle, 'slots': None}, [handle]])

    def test_subagent_handle_needs_agent_and_launch_and_no_slots(self) -> None:
        """A subagent names its agent and lower-case 32-hex launch, in its director's host and session."""
        handle = subagent()
        self.assertEqual(handle, {'type': 'declared', 'host': 'codex', 'session': SESSION_ID, 'agent': CODEX_AGENT,
                                  'launch': LAUNCH, 'hostThread': None, 'slots': None, 'hostProcess': None})
        for agent, launch in ((CODEX_AGENT, LAUNCH.upper()), (CODEX_AGENT, LAUNCH[:31]), (CODEX_AGENT, None),
                              (None, LAUNCH), (True, LAUNCH), (CODEX_AGENT + '\n', LAUNCH)):
            with self.subTest(agent=agent, launch=launch), self.assertRaisesRegex(ValueError, '^A declared subagent'):
                di.subagent_handle(director('codex'), agent, launch)
        for parent in (handle, {}, None, {**director(), 'slots': 1}):
            with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, 'from its valid declared director'):
                di.subagent_handle(parent, CODEX_AGENT, LAUNCH)
        self.assertInvalid([{**handle, 'slots': 2}, {**handle, 'hostThread': 'thread-1'},
                            {**handle, 'session': 's-0123'}, {**handle, 'agent': ''}])

    def test_codex_agent_path_accepted_and_bounded(self) -> None:
        """Codex paths have 1-4 segments, no dot segments, and at most 200 encoded bytes."""
        self.assertEqual((len(LONGEST_PATH), len(TOO_LONG_PATH)), (200, 201))
        for agent in (CODEX_AGENT, '/a/b/c/d', '/root', LONGEST_PATH, '/x/a..b'):
            with self.subTest(agent=agent):
                self.assertTrue(di.valid_agent(agent))
        for agent in ('/root/../x', '/root/./x', '/a/b/c/d/e', TOO_LONG_PATH, '/root/', 'root/x', '/root/a\n',
                      '/root/a\0', '/' + 'a' * 65, '//root'):
            with self.subTest(agent=agent):
                self.assertFalse(di.valid_agent(agent))
        with self.assertRaisesRegex(ValueError, 'at most 200 bytes'):
            di.subagent_handle(director('codex'), TOO_LONG_PATH, LAUNCH)

    def test_claude_agent_id_accepted(self) -> None:
        """A Claude Code agentId is a host token of at most 128 characters."""
        handle = subagent(CLAUDE_AGENT, 'claude-code')
        self.assertTrue(di.valid_declared(handle))
        self.assertEqual(handle['host'], 'claude-code')
        self.assertTrue(di.valid_agent('a' * 128))
        for agent in ('a' * 129, 'a b', '', '-a1', CLAUDE_AGENT + '\0', 17):
            with self.subTest(agent=agent):
                self.assertFalse(di.valid_agent(agent))

    def test_session_id_pattern(self) -> None:
        """A Sniper session id is s- and 16 lower-case hex digits, nothing more."""
        self.assertIsNotNone(di.SESSION.fullmatch(SESSION_ID))
        for session in ('s-0123456789ABCDEF', 's-0123456789abcde', 's-0123456789abcdef0', 'x-0123456789abcdef',
                        ' s-0123456789abcdef', SESSION_ID + '\n', None):
            with self.subTest(session=session), self.assertRaises(ValueError):
                di.director_handle('codex', session, None, 4)

    def test_identity_key_forms_and_bound(self) -> None:
        """One key per identity: declared, host (turn ignored) and process forms, at most 256 bytes."""
        self.assertEqual(di.identity_key(director()), f'declared:claude-code:{SESSION_ID}:director')
        self.assertEqual(di.identity_key(subagent()), f'declared:codex:{SESSION_ID}:{CODEX_AGENT}')
        self.assertEqual(di.identity_key(host_handle()), 'host:codex:thread-1')
        self.assertEqual(di.identity_key(host_handle(None)), 'host:codex:thread-1')
        self.assertEqual(di.identity_key({'type': 'process', **PROCESS}), f"process:4242:4242:{PROCESS['started']}")
        for host, agent in [(host, agent) for host in host_contract.HOSTS for agent in (LONGEST_PATH, 'a' * 128)]:
            with self.subTest(host=host, agent=agent):
                self.assertLessEqual(len(di.identity_key(subagent(agent, host)).encode()), 256)
        self.assertFalse(di.valid_agent(di.DIRECTOR_KEY))   # a subagent key never equals its director's
        self.assertNotEqual(di.identity_key(subagent(CLAUDE_AGENT, 'claude-code')), di.identity_key(director()))
        with self.assertRaises(ValueError):
            di.identity_key({**subagent(), 'slots': 2})

    def test_identity_basis_never_observed_for_ai(self) -> None:
        """AI identities are declared; only a local process is observed."""
        for handle in (director(), subagent(), subagent(CLAUDE_AGENT, 'claude-code'), host_handle(),
                       host_handle(None)):
            with self.subTest(handle=handle):
                self.assertEqual(di.identity_basis(handle), 'declared')
                self.assertNotIn('observed', di.identity_basis(handle))
        self.assertEqual(di.identity_basis({'type': 'process', **PROCESS}), 'process-observed')
        self.assertEqual(di.identity_basis(None), 'none')
        with self.assertRaises(ValueError):
            di.identity_basis({'type': 'declared'})

    def test_registered_identity_cases(self) -> None:
        """Section results accept a declared subagent or a historical host turn, nothing else."""
        self.assertTrue(di.registered_identity(subagent()))
        self.assertTrue(di.registered_identity(host_handle()))
        for handle in (director(), host_handle(None), {'type': 'process', **PROCESS}, None, {}, 'x',
                       {**subagent(), 'slots': 2}):
            with self.subTest(handle=handle):
                self.assertFalse(di.registered_identity(handle))

    def test_end_observation_tools_are_per_host(self) -> None:
        """A quoted end names a tool of the task's own host, as exact JSON."""
        self.assertEqual(set(di.END_TOOLS), set(host_contract.HOSTS))
        observed = di.parse_end_observation(end('TaskStop', 'killed'), 'claude-code')
        self.assertEqual(observed, di.EndObservation('TaskStop', 'killed'))
        self.assertEqual(di.parse_end_observation(end('wait_agent', 'completed'), 'codex').tool, 'wait_agent')
        with self.assertRaises(FrozenInstanceError):
            observed.status = 'completed'
        for text, host in ((end('wait_agent', 'completed'), 'claude-code'), (end('TaskStop', 'killed'), 'codex'),
                           (end('TaskStop', 'killed'), 'gemini'), ('{"tool": "TaskStop"}', 'claude-code'),
                           ('{"tool": "TaskStop", "status": "x", "extra": 1}', 'claude-code'),
                           ('{"tool": "TaskStop", "tool": "TaskStop", "status": "x"}', 'claude-code'),
                           ('{"tool": ["TaskStop"], "status": "x"}', 'claude-code'), ('not json', 'codex'),
                           ('["TaskStop", "killed"]', 'claude-code')):
            with self.subTest(text=text, host=host), self.assertRaisesRegex(ValueError, '^--end-observation is'):
                di.parse_end_observation(text, host)
        with self.assertRaisesRegex(ValueError, 'one of agent-notification, TaskStop, "status"'):
            di.parse_end_observation(end('wait_agent', 'x'), 'claude-code')

    def test_end_observation_status_bounded(self) -> None:
        """The status is the host's own words: one line, no NUL, 1-128 encoded bytes."""
        for status in ('x' * 128, 'completed', '\\u00e9' * 21):
            with self.subTest(status=status):
                self.assertTrue(di.parse_end_observation(end('agent-notification', status), 'claude-code').status)
        for status in ('x' * 129, '', 'a\\nb', 'a\\rb', 'a\\u0000b', '\\u00e9' * 22, 'a\\u2028b'):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'at most 128 bytes'):
                di.parse_end_observation(end('agent-notification', status), 'claude-code')
        with self.assertRaises(ValueError):
            di.parse_end_observation('{"tool": "TaskStop", "status": 7}', 'claude-code')

    def test_modes_include_declared(self) -> None:
        """M-088's host_contract hunks: the declared mode, the lazy validator branch and the message."""
        self.assertEqual(host_contract.MODES, ('unattended', 'supervised', 'declared', 'record-only'))
        for handle in (director(), subagent(), {**director(), 'hostProcess': dict(PROCESS)}):
            with self.subTest(handle=handle):
                self.assertTrue(host_contract.valid_handle(handle))
                self.assertEqual(host_contract.require_handle(handle), handle)
        self.assertFalse(host_contract.valid_handle({**subagent(), 'slots': 2}))
        with self.assertRaisesRegex(ValueError, r'a declared \{host, session, agent, launch, hostThread, slots, '
                                                r'hostProcess\}'):
            host_contract.require_handle({'type': 'declared'})
        tree = ast.parse(Path(inspect.getfile(host_contract)).read_text())
        top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse([node for node in top if 'declared_identity' in ast.unparse(node)])
        branch = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'valid_handle')
        self.assertIn('from studio.production.declared_identity import valid_declared', ast.unparse(branch))

    def test_historical_host_handle_still_valid(self) -> None:
        """Older records holding host and process handles still validate; adapter events stay host-only."""
        for handle in (host_handle(), host_handle(None), {'type': 'process', **PROCESS}):
            with self.subTest(handle=handle):
                self.assertTrue(host_contract.valid_handle(handle))
                self.assertEqual(host_contract.require_handle(handle), handle)
        event = {'type': 'started', 'taskId': 't1', 'epoch': 1, 'token': LAUNCH, 'handle': host_handle(),
                 'sequence': 0, 'receipts': [], 'failure': None, 'usage': None}
        self.assertEqual(host_contract.parse_event(event).handle, host_handle())
        with self.assertRaisesRegex(ValueError, 'exact host handle'):
            host_contract.parse_event({**event, 'handle': subagent()})

    def test_director_handle_accepts_host_process(self) -> None:
        """D-E: a director's hostProcess is None or {pid, pgid, started} under the process rules minus type."""
        self.assertEqual(list(inspect.signature(di.director_handle).parameters),
                         ['host', 'session', 'host_thread', 'slots'])
        self.assertIsNone(director()['hostProcess'])
        filled = {**director(), 'hostProcess': dict(PROCESS)}
        self.assertTrue(di.valid_declared(filled))
        self.assertEqual(di.identity_key(filled), di.identity_key(director()))
        self.assertEqual(di.identity_basis(filled), 'declared')
        self.assertTrue(di.valid_declared({**director(), 'hostProcess': {**PROCESS, 'started': 's' * 64}}))
        bad = [{'type': 'process', **PROCESS}, {**PROCESS, 'pid': 0}, {**PROCESS, 'pgid': 2 ** 31 + 1},
               {**PROCESS, 'pid': True}, {**PROCESS, 'started': ''}, {**PROCESS, 'started': 's' * 65},
               {**PROCESS, 'started': 'a\nb'}, {'pid': 1, 'started': 'x'}, {**PROCESS, 'extra': 1}, [4242, 4242]]
        self.assertInvalid([{**director(), 'hostProcess': value} for value in bad])

    def test_worker_handle_refuses_host_process(self) -> None:
        """D-E: a subagent (worker) handle's hostProcess is always None."""
        worker = {**subagent(), 'hostProcess': dict(PROCESS)}
        self.assertInvalid([worker, {**subagent(CLAUDE_AGENT, 'claude-code'), 'hostProcess': dict(PROCESS)}])
        self.assertFalse(di.registered_identity(worker))
        with self.assertRaises(ValueError):
            di.identity_key(worker)


if __name__ == '__main__':
    unittest.main()
