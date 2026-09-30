"""Declared identities link to exactly one transcript owner, or stay unknown with a named reason (P3b-11, M-108).

Synthetic transcripts in temporary directories, in the host-observed shapes (Claude Code subagent lines carry
``agentId``; a spawned Codex subagent's ``session_meta`` names ``source.subagent.thread_spawn``). No real
transcript is read. The declared director rows are passed in as ``ai_usage`` will pass them at M-108.
"""
from __future__ import annotations

import json
import unittest

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
import agent_usage
from _budget_fixture import FINGERPRINT
from _status_fixture import batch_record, record_usage, run_task, temporary_directory, usage
from studio.native_budget_identity_links import (NO_HOST_THREAD, NO_ROLLOUT, SUBAGENT_RULES, link_key,
                                                 unlinked_reason, unlinked_reasons)
from studio.native_budget_schema import validate_record
from studio.native_budget_usage import ai_usage, authority_usage, transcript_usage
from studio.production import claims, host_contract
from studio.production.declared_identity import director_handle, subagent_handle
from studio.production.task_schema import is_ai
from studio.production.tasks import tasks_of

SESSION = 's-00000000000000a1'
DIRECTOR_THREAD = 'TEST-director-thread'
LAUNCHES = ('a' * 32, 'b' * 32, 'c' * 32)
CODEX_USAGE = {'input_tokens': 100, 'cached_input_tokens': 60, 'cache_write_input_tokens': 0, 'output_tokens': 5,
               'reasoning_output_tokens': 0}
CLAUDE_USAGE = {'input_tokens': 1, 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3, 'output_tokens': 4}


class DeclaredCase(unittest.TestCase):
    """A batch whose director enrolled with a declared handle on ``HOST`` (host thread ``THREAD``)."""

    HOST = 'codex'
    THREAD: str | None = DIRECTOR_THREAD

    def setUp(self) -> None:
        """A TEST batch whose director enrolled with a declared handle, and a private transcript folder."""
        self.record = batch_record(slots=6)
        self.director = director_handle(self.HOST, SESSION, self.THREAD, 3)
        claims.enroll_director(self.record, claims.Enrollment('director', self.director, 'v1', FINGERPRINT), 1.0)
        self.directory = temporary_directory(self)

    def subagent(self, task_id: str, agent: str, launch: str = LAUNCHES[0]) -> dict:
        """Run a declared author (``*-A`` on clip A, ``*-B`` on clip B) or repair of clip A, completed at 400 s."""
        kind = 'repairCycle' if task_id.startswith('repair') else 'author'
        values = {'clip_id': 'B'} if task_id.endswith('-B') else {}
        handle = subagent_handle(self.director, agent, launch)
        return run_task(self.record, (task_id, kind, values), handle, (10.0, 400.0))

    def transcripts(self, files: dict) -> dict:
        """``collect_files`` over TEST transcripts written from ``{name: [row, ...]}``."""
        paths = []
        for name, rows in files.items():
            paths.append(self.directory / name)
            paths[-1].write_text(''.join(json.dumps(row) + '\n' for row in rows))
        start = self.record['startEpoch']
        return agent_usage.collect_files(paths, (start, start + 10_000.0))

    def linked(self, found: dict, clip_id: str | None = None) -> dict:
        """The transcript usage with this batch's declared director row, as ``ai_usage`` passes it at M-108."""
        validate_record(self.record)
        charged = [task for task in tasks_of(self.record).values() if is_ai(task) and task['charged']]
        return transcript_usage(found, charged, clip_id, [self.record['production']['tasks']['director']])

    def codex_meta(self, thread: str, spawn: tuple[str, str] | None = None) -> dict:
        """A rollout's session_meta; ``spawn`` = (parent thread, agent path) for a spawned subagent."""
        payload = {'id': thread, 'source': 'cli'}
        if spawn is not None:
            payload = {'id': thread, 'parent_thread_id': spawn[0], 'agent_path': spawn[1], 'source': {'subagent': {
                'thread_spawn': {'parent_thread_id': spawn[0], 'depth': 1, 'agent_path': spawn[1],
                                 'agent_nickname': 'TEST', 'agent_role': None}}}}
        return {'timestamp': str(self.record['startEpoch'] + 1), 'type': 'session_meta', 'payload': payload}

    def codex_record(self, thread: str, response: str) -> dict:
        """One per-response usage record of ``thread`` (100 input, 60 cached, 5 output)."""
        return {'timestamp': str(self.record['startEpoch'] + 100), 'type': 'token_usage_record', 'payload': {
            'thread_id': thread, 'turn_id': f'{thread}-turn', 'response_id': response, 'usage': CODEX_USAGE}}

    def claude_line(self, message: str, agent: str | None = None) -> dict:
        """One Claude Code assistant line of the director's session (a subagent transcript names its agentId)."""
        row = {'type': 'assistant', 'timestamp': str(self.record['startEpoch'] + 200), 'sessionId': DIRECTOR_THREAD,
               'message': {'id': message, 'usage': CLAUDE_USAGE}}
        return {**row, 'agentId': agent} if agent is not None else row


class ClaudeCodeLinkTests(DeclaredCase):
    """Claude Code: the director by its declared host thread, a subagent by its agent id."""

    HOST = 'claude-code'

    def test_claude_director_links_by_host_thread(self) -> None:
        """The director links to its declared session id, at thread level, with exact counts."""
        found = self.transcripts({'director.jsonl': [self.claude_line('m1'), self.claude_line('m2')]})
        run = ai_usage(self.record, None, found)['usage']['transcripts']
        self.assertEqual([(row['thread'], row['level'], row['tasks'], row['records']) for row in run['links']],
                         [(DIRECTOR_THREAD, 'thread', ['director'], 2)])
        self.assertEqual(run['totals'], {'inputTokens': 12, 'cachedInputTokens': 6, 'outputTokens': 8,
                                         'reasoningTokens': None})
        self.assertEqual(link_key(self.director, [], {}), ('claude-code', DIRECTOR_THREAD, '*'))

    def test_claude_subagent_links_by_agent_id(self) -> None:
        """A subagent links to its agentId transcript; the director's own lines stay the director's."""
        self.subagent('author-A', 'agent-a1')
        found = self.transcripts({'director.jsonl': [self.claude_line('m1')],
                                  'agent-a1.jsonl': [self.claude_line('m2', 'agent-a1'),
                                                     self.claude_line('m3', 'agent-a1')]})
        clip = ai_usage(self.record, 'A', found)['usage']['transcripts']
        self.assertEqual([(row['thread'], row['tasks'], row['records']) for row in clip['links']],
                         [('agent-a1', ['author-A'], 2)])
        self.assertEqual((clip['totals']['outputTokens'], clip['unknownBecause']), (8, []))
        run = ai_usage(self.record, None, found)['usage']['transcripts']
        self.assertEqual((run['unlinked']['records'], run['linked']['records']), (0, 3))


class CodexLinkTests(DeclaredCase):
    """Codex: the director by its declared thread, a subagent by the one rollout spawned under it with its path."""

    def test_codex_subagent_links_by_parent_and_path(self) -> None:
        """The one rollout spawned from the director thread with the agent path links; others do not."""
        self.subagent('author-A', '/root/author_a')
        found = self.transcripts({
            'director.jsonl': [self.codex_meta(DIRECTOR_THREAD), self.codex_record(DIRECTOR_THREAD, 'r0')],
            'mine.jsonl': [self.codex_meta('TEST-sub-1', (DIRECTOR_THREAD, '/root/author_a')),
                           self.codex_record('TEST-sub-1', 'r1')],
            'other-director.jsonl': [self.codex_meta('TEST-sub-2', ('TEST-other-director', '/root/author_a')),
                                     self.codex_record('TEST-sub-2', 'r2')],
            'other-path.jsonl': [self.codex_meta('TEST-sub-3', (DIRECTOR_THREAD, '/root/author_b')),
                                 self.codex_record('TEST-sub-3', 'r3')]})
        run = self.linked(found)
        self.assertEqual({row['thread']: row['tasks'] for row in run['links']},
                         {DIRECTOR_THREAD: ['director'], 'TEST-sub-1': ['author-A']})
        self.assertEqual((run['unlinked']['records'], run['linked']['inputTokens']), (2, 200))
        self.assertEqual(run['unknownBecause'], ['2 record(s) name no task of this run'])
        clip = self.linked(found, 'A')
        self.assertEqual((clip['totals']['inputTokens'], clip['unknownBecause']), (100, []))

    def test_codex_ambiguous_path_is_unknown_with_reason(self) -> None:
        """Two rollouts with the same path under the director thread link nothing, with the reason."""
        self.subagent('author-A', '/root/author_a')
        spawned = (DIRECTOR_THREAD, '/root/author_a')
        found = self.transcripts({'one.jsonl': [self.codex_meta('TEST-sub-1', spawned),
                                                self.codex_record('TEST-sub-1', 'r1')],
                                  'two.jsonl': [self.codex_meta('TEST-sub-2', spawned),
                                                self.codex_record('TEST-sub-2', 'r2')]})
        clip = self.linked(found, 'A')
        self.assertEqual(clip['links'], [])
        self.assertIsNone(clip['totals']['inputTokens'])
        self.assertIn('2 rollouts name this agent path under the director thread', clip['unknownBecause'])
        self.assertIn('1 host task(s) have no transcript record', clip['unknownBecause'])
        one = {'TEST-sub-1': found['threads']['TEST-sub-1']}
        self.assertEqual(link_key(self.record['production']['tasks']['author-A']['handle'], self.directors(), one),
                         ('codex', 'TEST-sub-1', '*'))
        self.assertEqual(unlinked_reason(self.record['production']['tasks']['author-A']['handle'],
                                         self.directors(), {}), NO_ROLLOUT)

    def test_reused_agent_counted_once(self) -> None:
        """An author and its repair on the same agent are one execution and one transcript link."""
        self.subagent('author-A', '/root/author_a')
        self.subagent('repair-A', '/root/author_a', LAUNCHES[1])
        record_usage(self.record, 'author-A', usage(1000, 800, 50), 400.0)
        record_usage(self.record, 'repair-A', usage(1500, 900, 70), 400.0)
        tasks = [row for row in tasks_of(self.record).values() if row['id'] != 'director']
        found = authority_usage(tasks)
        self.assertEqual((found['executions'], found['tasksSharingAnExecution']), (1, 1))
        self.assertEqual(found['totals']['inputTokens'], 1500)
        rollout = self.transcripts({'sub.jsonl': [self.codex_meta('TEST-sub-1', (DIRECTOR_THREAD, '/root/author_a')),
                                                  self.codex_record('TEST-sub-1', 'r1')]})
        clip = self.linked(rollout, 'A')
        self.assertEqual([(row['tasks'], row['records']) for row in clip['links']], [(['author-A', 'repair-A'], 1)])
        self.assertEqual(clip['totals']['inputTokens'], 100)

    def test_unknown_never_zero(self) -> None:
        """A link without records, or no link at all, leaves the totals unknown, never zero."""
        self.subagent('author-A', '/root/author_a')
        linked_without_records = self.transcripts({'sub.jsonl': [
            self.codex_meta('TEST-sub-1', (DIRECTOR_THREAD, '/root/author_a'))]})
        clip = self.linked(linked_without_records, 'A')
        self.assertEqual(clip['totals'], dict.fromkeys(('inputTokens', 'outputTokens', 'cachedInputTokens',
                                                        'reasoningTokens')))
        self.assertEqual(clip['unknownBecause'], ['1 host task(s) have no transcript record',
                                                  'no transcript record was observed'])
        unlinked = self.linked(self.transcripts({'none.jsonl': [self.codex_record('TEST-sub-9', 'r9')]}), 'A')
        self.assertIsNone(unlinked['totals']['inputTokens'])
        self.assertIn(NO_ROLLOUT, unlinked['unknownBecause'])

    def test_codex_director_links_by_its_declared_thread(self) -> None:
        """A Codex director links to the thread it declared at enrolment."""
        found = self.transcripts({'director.jsonl': [self.codex_meta(DIRECTOR_THREAD),
                                                     self.codex_record(DIRECTOR_THREAD, 'r0')]})
        run = ai_usage(self.record, None, found)['usage']['transcripts']
        self.assertEqual([(row['host'], row['thread'], row['tasks']) for row in run['links']],
                         [('codex', DIRECTOR_THREAD, ['director'])])
        self.assertEqual((run['totals']['inputTokens'], run['unknownBecause']), (100, []))

    def test_rollout_threads_name_the_spawning_parent_and_agent_path(self) -> None:
        """collect_files reports each rollout thread with its thread_spawn parent and agent path."""
        found = self.transcripts({
            'sub.jsonl': [self.codex_meta('TEST-sub-1', (DIRECTOR_THREAD, '/root/a'))],
            'root.jsonl': [self.codex_meta('TEST-root')],
            'no-meta.jsonl': [self.codex_record('TEST-bare', 'r1')],
            'claude.jsonl': [self.claude_line('m1')],
            'x1.jsonl': [self.codex_meta('TEST-sub-2', (DIRECTOR_THREAD, '/root/b'))],
            'x2.jsonl': [self.codex_meta('TEST-sub-2', (DIRECTOR_THREAD, '/root/c'))]})
        self.assertEqual(found['threads'], {
            'TEST-sub-1': {'parent': DIRECTOR_THREAD, 'agentPath': '/root/a'},
            'TEST-root': {'parent': None, 'agentPath': None},
            'TEST-sub-2': {'parent': None, 'agentPath': None}})   # its two files disagree: it names neither

    def directors(self) -> list[dict]:
        """This batch's one declared director row."""
        return [self.record['production']['tasks']['director']]


class MissingThreadTests(DeclaredCase):
    """A director enrolled without its host thread: it and its Codex subagents link nothing, with the reason."""

    THREAD = None

    def test_missing_host_thread_is_unknown_with_reason(self) -> None:
        """Without a declared host thread the director and its Codex subagents link nothing."""
        self.subagent('author-A', '/root/author_a')
        found = self.transcripts({'sub.jsonl': [self.codex_meta('TEST-sub-1', (DIRECTOR_THREAD, '/root/author_a')),
                                                self.codex_record('TEST-sub-1', 'r1')]})
        run = self.linked(found)
        self.assertEqual(run['links'], [])
        self.assertIsNone(run['totals']['inputTokens'])
        self.assertEqual(run['unknownBecause'], ['2 host task(s) have no transcript record',
                                                 '1 record(s) name no task of this run', NO_HOST_THREAD])
        self.assertEqual(unlinked_reason(self.director, [], {}), NO_HOST_THREAD)


class LinkRuleTests(unittest.TestCase):
    """The rules on their own: every handle kind, the director rows, the host table, the rollout threads."""

    DIRECTOR = director_handle('codex', SESSION, DIRECTOR_THREAD, 3)

    def test_host_and_process_handles(self) -> None:
        """Host handles keep their exact owner; process and missing handles link nothing, with a reason."""
        host = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread', 'turn': 'TEST-turn'}
        process = {'type': 'process', 'pid': 7001, 'pgid': 7001, 'started': 'Sun Sep 27 10:00:00 2026'}
        self.assertEqual(link_key(host, [], {}), ('codex', 'TEST-thread', 'TEST-turn'))
        self.assertEqual((link_key(process, [], {}), link_key(None, [], {})), (None, None))
        self.assertEqual((unlinked_reason(process, [], {}), unlinked_reason(None, [], {})),
                         ('a process handle names no host transcript', 'a missing handle names no host transcript'))
        with self.assertRaisesRegex(ValueError, 'it has no unlinked reason'):
            unlinked_reason(host, [], {})

    def test_codex_subagent_needs_exactly_one_director_row_of_its_session(self) -> None:
        """Zero or two director rows for the session link nothing, with the count named."""
        agent = subagent_handle(self.DIRECTOR, '/root/author_a', LAUNCHES[0])
        threads = {'TEST-sub-1': {'parent': DIRECTOR_THREAD, 'agentPath': '/root/author_a'}}
        row = {'id': 'director', 'handle': self.DIRECTOR}
        other = {'id': 'director-2', 'handle': director_handle('codex', 's-00000000000000b2', DIRECTOR_THREAD, 3)}
        self.assertEqual(link_key(agent, [other, row], threads), ('codex', 'TEST-sub-1', '*'))
        self.assertEqual(unlinked_reason(agent, [other], threads), f'0 declared director rows name session {SESSION}')
        self.assertEqual(unlinked_reason(agent, [row, dict(row)], threads),
                         f'2 declared director rows name session {SESSION}')
        tasks = [{'id': 't1', 'handle': agent}, {'id': 't2', 'handle': {**agent, 'launch': LAUNCHES[1]}},
                 {'id': 't3', 'handle': None}]
        self.assertEqual(unlinked_reasons(tasks, [], threads), [f'0 declared director rows name session {SESSION}'])

    def test_every_host_has_a_subagent_rule(self) -> None:
        """Every host the contract knows has exactly one subagent link rule."""
        self.assertEqual(set(SUBAGENT_RULES), set(host_contract.HOSTS))


if __name__ == '__main__':
    unittest.main()
