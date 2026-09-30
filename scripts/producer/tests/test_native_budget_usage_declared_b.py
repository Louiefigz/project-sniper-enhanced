"""Declared links across sessions and rollouts (X210 fix round; the L-V review's probes adopted as tests).

A host thread two director sessions declared is ambiguous: no rollout is borrowed across sessions, the totals are not
exact (named reason), and the conversation's director usage counts once. Also: executions per session and thread,
cross-host sessions, missing or disagreeing rollout metadata, distinct reasons, the first session_meta, and the
``agent_usage`` CLI's unchanged output. Synthetic rollouts in temporary directories; no real transcript is read.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
import agent_usage
from _status_fixture import temporary_directory
from studio.native_budget_identity_links import (DISAGREEING, NO_HOST_THREAD, NO_ROLLOUT, SHARED_THREAD, link_key,
                                                 link_reasons, unlinked_reason)
from studio.native_budget_usage import authority_usage, transcript_usage
from studio.production.declared_identity import director_handle, subagent_handle

S1, S2 = 's-00000000000000a1', 's-00000000000000b2'
LAUNCH = ('a' * 32, 'b' * 32)
PREVIOUS_CLI_KEYS = {'window', 'agents', 'total', 'repeatsDropped', 'unreadable', 'partialFinalLines',
                     'forksWithoutParentBase', 'recordsWithoutId', 'compactions', 'note'}


def director_row(task_id: str, host: str, session: str, thread: str | None) -> dict:
    """A declared director task row as sessions.declared_directors returns it."""
    return {'id': task_id, 'clipId': None, 'handle': director_handle(host, session, thread, 3), 'usage': None}


def task(task_id: str, clip: str | None, handle: dict, usage: dict | None = None) -> dict:
    """A minimal charged task for the usage functions."""
    return {'id': task_id, 'clipId': clip, 'handle': handle, 'usage': usage}


def usage_of(inputs: int) -> dict:
    """A cumulative host report."""
    return {'inputTokens': inputs, 'cachedInputTokens': 0, 'outputTokens': 5, 'reasoningTokens': 0}


class Rollouts(unittest.TestCase):
    """Synthetic Codex rollouts and Claude Code lines in a private folder."""

    def rollouts(self, rows: dict) -> dict:
        """``collect_files`` over ``{name: [rows]}`` for the window 0..10,000 s."""
        directory = temporary_directory(self)
        paths = []
        for name, lines in rows.items():
            paths.append(directory / name)
            paths[-1].write_text(''.join(json.dumps(line) + '\n' for line in lines))
        return agent_usage.collect_files(paths, (0.0, 10_000.0))

    @staticmethod
    def meta_row(thread: str, spawn: tuple[str, str] | None) -> dict:
        """A Codex session_meta row; ``spawn`` = (parent thread, agent path) for a spawned subagent."""
        payload = {'id': thread, 'source': 'cli'}
        if spawn:
            payload['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': spawn[0], 'agent_path': spawn[1]}}}
        return {'timestamp': '1', 'type': 'session_meta', 'payload': payload}

    @staticmethod
    def record_row(thread: str, response: str) -> dict:
        """One Codex per-response usage record (10 input, 1 output)."""
        return {'timestamp': '100', 'type': 'token_usage_record', 'payload': {
            'thread_id': thread, 'turn_id': 't', 'response_id': response,
            'usage': {'input_tokens': 10, 'cached_input_tokens': 0, 'cache_write_input_tokens': 0,
                      'output_tokens': 1, 'reasoning_output_tokens': 0}}}

    @staticmethod
    def claude_line(thread: str, message: str) -> dict:
        """One Claude Code assistant line of conversation ``thread``."""
        return {'type': 'assistant', 'timestamp': '200', 'sessionId': thread, 'message': {'id': message, 'usage': {
            'input_tokens': 1, 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3, 'output_tokens': 4}}}


class SharedThreadTests(Rollouts):
    """One host thread declared by two sessions of a batch (X210 ruling)."""

    def test_no_rollout_is_borrowed_across_sessions(self) -> None:
        """A subagent of either session links nothing: the rollout under the shared thread may be the other's."""
        d1, d2 = director_row('dir-1', 'codex', S1, 'T'), director_row('dir-2', 'codex', S2, 'T')
        old = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        new = subagent_handle(d2['handle'], '/root/author', LAUNCH[1])
        found = self.rollouts({'old.jsonl': [self.meta_row('R-old', ('T', '/root/author')),
                                             self.record_row('R-old', 'r1')]})
        shared = SHARED_THREAD.format(count=2, thread='T')
        self.assertEqual([link_key(handle, [d1, d2], found['threads']) for handle in (old, new)], [None, None])
        self.assertEqual(unlinked_reason(new, [d1, d2], found['threads']), shared)
        clip = transcript_usage(found, [task('author-old', 'A', old), task('author-new', 'A', new)], 'A', [d1, d2])
        self.assertEqual((clip['links'], clip['totals']['inputTokens']), ([], None))
        self.assertIn(shared, clip['unknownBecause'])

    def test_directors_of_one_thread_link_once_and_are_not_exact(self) -> None:
        """Both directors link to the one conversation, counted once; the totals are not exact, with the reason."""
        d1, d2 = director_row('dir-1', 'claude-code', S1, 'C'), director_row('dir-2', 'claude-code', S2, 'C')
        found = self.rollouts({'c.jsonl': [self.claude_line('C', 'm1'), self.claude_line('C', 'm2')]})
        run = transcript_usage(found, [d1, d2], None, [d1, d2])
        self.assertEqual([(row['thread'], row['tasks'], row['records']) for row in run['links']],
                         [('C', ['dir-1', 'dir-2'], 2)])
        self.assertEqual((run['totals']['inputTokens'], run['knownPartial']['inputTokens']), (None, 12))
        self.assertEqual(run['unknownBecause'], [SHARED_THREAD.format(count=2, thread='C')])

    def test_authority_counts_one_conversation_once(self) -> None:
        """Cumulative director reports 100 then 250 of one conversation read 250 (not 350), shown as not exact."""
        d1, d2 = director_row('dir-1', 'claude-code', S1, 'C'), director_row('dir-2', 'claude-code', S2, 'C')
        found = authority_usage([{**d1, 'usage': usage_of(100)}, {**d2, 'usage': usage_of(250)}])
        self.assertEqual((found['executions'], found['tasksSharingAnExecution']), (1, 1))
        self.assertEqual((found['totals']['inputTokens'], found['knownPartial']['inputTokens']), (None, 250))
        self.assertEqual(found['unknownBecause'], [SHARED_THREAD.format(count=2, thread='C')])

    def test_directors_on_distinct_threads_are_two_exact_executions(self) -> None:
        """Two sessions' directors on their own threads are two executions, summed, exact."""
        d1, d2 = director_row('dir-1', 'codex', S1, 'T1'), director_row('dir-2', 'codex', S2, 'T2')
        found = authority_usage([{**d1, 'usage': usage_of(100)}, {**d2, 'usage': usage_of(100)}])
        self.assertEqual((found['executions'], found['totals']['inputTokens'], found['unknownBecause']), (2, 200, []))

    def test_subagents_of_two_sessions_with_one_agent_path_are_two_executions(self) -> None:
        """The session is part of a subagent's execution: one agent path in two sessions is two agents."""
        d1, d2 = director_row('dir-1', 'codex', S1, 'T1'), director_row('dir-2', 'codex', S2, 'T2')
        a1 = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        a2 = subagent_handle(d2['handle'], '/root/author', LAUNCH[1])
        found = authority_usage([task('a1', 'A', a1, usage_of(100)), task('a2', 'A', a2, usage_of(100))])
        self.assertEqual((found['executions'], found['totals']['inputTokens']), (2, 200))

    def test_two_directors_on_distinct_threads_link_their_own_rollouts(self) -> None:
        """A takeover chain on Codex: each session's subagent links through its own director row."""
        d1, d2 = director_row('dir-1', 'codex', S1, 'T1'), director_row('dir-2', 'codex', S2, 'T2')
        a1 = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        a2 = subagent_handle(d2['handle'], '/root/author', LAUNCH[1])
        threads = {'R1': {'parent': 'T1', 'agentPath': '/root/author'},
                   'R2': {'parent': 'T2', 'agentPath': '/root/author'}}
        self.assertEqual((link_key(a1, [d1, d2], threads), link_key(a2, [d1, d2], threads)),
                         (('codex', 'R1', '*'), ('codex', 'R2', '*')))

    def test_cross_host_sessions(self) -> None:
        """A Codex session, then a Claude Code session: each links by its own host's rule."""
        d1, d2 = director_row('dir-1', 'codex', S1, 'T1'), director_row('dir-2', 'claude-code', S2, 'C2')
        codex_agent = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        claude_agent = subagent_handle(d2['handle'], 'a1b2c3d4', LAUNCH[1])
        threads = {'R1': {'parent': 'T1', 'agentPath': '/root/author'}}
        self.assertEqual([link_key(handle, [d1, d2], threads) for handle in (codex_agent, claude_agent, d2['handle'])],
                         [('codex', 'R1', '*'), ('claude-code', 'a1b2c3d4', '*'), ('claude-code', 'C2', '*')])


class RolloutTests(Rollouts):
    """Rollout metadata: missing, disagreeing, several, first-wins."""

    def test_missing_session_meta_names_no_rollout(self) -> None:
        """Without a usable session_meta no thread is named: the subagent is unknown with the reason."""
        d1 = director_row('dir-1', 'codex', S1, 'T1')
        agent = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        found = self.rollouts({'nometa.jsonl': [self.record_row('R1', 'r1')],
                               'badmeta.jsonl': [{'type': 'session_meta', 'payload': {'id': 7}},
                                                 self.record_row('R2', 'r2')]})
        run = transcript_usage(found, [task('author-A', 'A', agent)], None, [d1])
        self.assertEqual((found['threads'], run['totals']['inputTokens']), ({}, None))
        self.assertIn(NO_ROLLOUT, run['unknownBecause'])

    def test_disagreeing_files_give_their_own_reason(self) -> None:
        """Two files of one thread naming different paths: unknown, and the reason says they disagree (review n1)."""
        d1 = director_row('dir-1', 'codex', S1, 'T1')
        agent = subagent_handle(d1['handle'], '/root/author', LAUNCH[0])
        found = self.rollouts({'a.jsonl': [self.meta_row('R1', ('T1', '/root/author'))],
                               'b.jsonl': [self.meta_row('R1', ('T1', '/root/other'))]})
        self.assertEqual(unlinked_reason(agent, [d1], found['threads']), DISAGREEING.format(count=1))

    def test_distinct_unlinked_reasons_are_all_reported(self) -> None:
        """An ambiguous path and a missing rollout: both reasons reach unknownBecause."""
        d1 = director_row('dir-1', 'codex', S1, 'T1')
        a = subagent_handle(d1['handle'], '/root/a', LAUNCH[0])
        b = subagent_handle(d1['handle'], '/root/b', LAUNCH[1])
        found = self.rollouts({'x.jsonl': [self.meta_row('R1', ('T1', '/root/a'))],
                               'y.jsonl': [self.meta_row('R2', ('T1', '/root/a'))]})
        run = transcript_usage(found, [task('author-a', 'A', a), task('author-b', 'A', b)], None, [d1])
        self.assertIn('2 rollouts name this agent path under the director thread', run['unknownBecause'])
        self.assertIn(NO_ROLLOUT, run['unknownBecause'])
        self.assertEqual(len(link_reasons([task('a', 'A', a), task('b', 'A', b)], [d1], found['threads'])), 2)

    def test_a_subagent_of_a_threadless_director_names_the_reason(self) -> None:
        """A Codex subagent whose director declared no host thread links nothing, with that reason of its own."""
        d1 = director_row('dir-1', 'codex', S1, None)
        agent = subagent_handle(d1['handle'], '/root/a', LAUNCH[0])
        threads = {'R1': {'parent': None, 'agentPath': '/root/a'}}
        self.assertEqual((link_key(agent, [d1], threads), unlinked_reason(agent, [d1], threads)),
                         (None, NO_HOST_THREAD))

    def test_first_session_meta_names_the_rollout(self) -> None:
        """A rollout whose first session_meta names R1 and a later one R9 is R1's (A6u's first-wins rule)."""
        found = self.rollouts({'x.jsonl': [self.meta_row('R1', ('T1', '/root/a')), self.meta_row('R9', None)]})
        self.assertEqual(found['threads'], {'R1': {'parent': 'T1', 'agentPath': '/root/a'}})


class CliTests(Rollouts):
    """The agent_usage CLI keeps its output shape; rollout identities are never printed (X210 item 6)."""

    def test_cli_output_keeps_its_shape(self) -> None:
        """Same keys as before V2; no rollout thread, parent or agent path in the output."""
        directory = temporary_directory(self)
        rollout = directory / 'x.jsonl'
        rollout.write_text(json.dumps(self.meta_row('TEST-R1', ('TEST-T1', '/root/author'))) + '\n'
                           + json.dumps(self.record_row('TEST-R1', 'r1')) + '\n')
        printed = io.StringIO()
        with mock.patch('sys.argv', ['agent_usage.py', '--since', '0', str(rollout)]), \
                contextlib.redirect_stdout(printed):
            agent_usage.main()
        output = json.loads(printed.getvalue())
        self.assertEqual(set(output), PREVIOUS_CLI_KEYS)
        for identity in ('TEST-T1', '/root/author'):
            self.assertNotIn(identity, printed.getvalue())
        self.assertEqual(output['total']['output'], 1)


if __name__ == '__main__':
    unittest.main()
