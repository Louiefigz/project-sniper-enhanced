"""Token counters are windowed, deduplicated across files and never double-counted; missing is unknown."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import agent_usage as usage

WINDOW = (usage.parse_time('2026-09-27T14:00:00Z'), usage.parse_time('2026-09-27T15:00:00Z'))


def codex_event(stamp: str, total_input: int, cached: int, output: int, reasoning: int) -> dict:
    return {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
        'total_token_usage': {'input_tokens': total_input, 'cached_input_tokens': cached,
                              'cache_write_input_tokens': 0, 'output_tokens': output,
                              'reasoning_output_tokens': reasoning}}}}


def claude_line(stamp: str, message_id: str, output: int, thinking: int = 0) -> dict:
    return {'type': 'assistant', 'timestamp': stamp, 'message': {'id': message_id, 'usage': {
        'input_tokens': 2, 'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 1000,
        'output_tokens': output, 'output_tokens_details': {'thinking_tokens': thinking}}}}


class AgentUsageTests(unittest.TestCase):
    """Synthetic transcripts in the two real host formats."""

    def write(self, rows: list[dict]) -> Path:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        file = directory / 'session.jsonl'
        file.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return file

    def test_codex_window_delta_subtracts_the_pre_window_total(self) -> None:
        rows = [codex_event('2026-09-27T13:59:00Z', 1000, 400, 50, 20),
                codex_event('2026-09-27T14:10:00Z', 3000, 2000, 150, 60),
                codex_event('2026-09-27T14:20:00Z', 6000, 4500, 400, 100),
                codex_event('2026-09-27T15:30:00Z', 9000, 7000, 900, 300)]
        result = usage.file_usage(self.write(rows), WINDOW)
        self.assertEqual(result['cachedInput'], 4100)
        self.assertEqual(result['nonCachedInput'], 5000 - 4100)
        self.assertEqual((result['output'], result['reasoningOutputSubset']), (350, 80))

    def test_codex_counter_reset_starts_a_new_segment(self) -> None:
        rows = [codex_event('2026-09-27T14:05:00Z', 1000, 0, 10, 0),
                codex_event('2026-09-27T14:06:00Z', 200, 0, 5, 0)]
        result = usage.file_usage(self.write(rows), WINDOW)
        self.assertEqual((result['nonCachedInput'], result['output'], result['segments']), (1200, 15, 2))

    def test_claude_message_blocks_are_counted_once(self) -> None:
        rows = [claude_line('2026-09-27T14:01:00Z', 'msg-1', 300, 120),
                claude_line('2026-09-27T14:01:01Z', 'msg-1', 300, 120),
                claude_line('2026-09-27T14:02:00Z', 'msg-2', 50),
                claude_line('2026-09-27T16:00:00Z', 'msg-3', 999)]
        result = usage.file_usage(self.write(rows), WINDOW)
        self.assertEqual((result['messages'], result['output'], result['reasoningOutputSubset']), (2, 350, 120))
        self.assertEqual((result['cachedInput'], result['cacheWriteInput']), (2000, 200))

    def test_malformed_lines_are_errors(self) -> None:
        file = self.write([])
        file.write_text('{"type": "assistant"\n')
        with self.assertRaisesRegex(ValueError, 'malformed transcript line'):
            usage.file_usage(file, WINDOW)


def claude_row(stamp: str, message_id: str, session: str, usage_fields: dict, **extra: str) -> dict:
    return {'type': 'assistant', 'timestamp': stamp, 'sessionId': session,
            'message': {'id': message_id, 'usage': usage_fields}, **extra}


def codex_record(stamp: str, response: str, turn: str, fields: tuple[int, int, int, int]) -> dict:
    total, cached, written, output = fields
    return {'timestamp': stamp, 'type': 'token_usage_record', 'payload': {
        'thread_id': 'TEST-thread', 'turn_id': turn, 'session_id': 'TEST-thread', 'response_id': response,
        'usage': {'input_tokens': total, 'cached_input_tokens': cached, 'cache_write_input_tokens': written,
                  'output_tokens': output, 'reasoning_output_tokens': 1, 'total_tokens': total + output}}}


class ReplayAndUnknownTests(unittest.TestCase):
    """Replays across files count once; a count the host did not report is unknown."""

    def write(self, name: str, rows: list[dict]) -> Path:
        directory = getattr(self, 'directory', None) or Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = directory
        file = directory / name
        file.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return file

    def test_a_resumed_claude_session_replaying_messages_counts_them_once(self) -> None:
        full = {'input_tokens': 5, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 100,
                'output_tokens': 7}
        first = self.write('a.jsonl', [claude_row('2026-09-27T14:01:00Z', 'msg-1', 'S1', full)])
        second = self.write('b.jsonl', [claude_row('2026-09-27T14:01:00Z', 'msg-1', 'S1', full),
                                        claude_row('2026-09-27T14:05:00Z', 'msg-2', 'S1', full)])
        units, repeats = usage.collect([first, second], WINDOW)
        total = usage.totals(units)
        self.assertEqual((len(units), repeats, total['output'], total['cachedInput']), (2, 1, 14, 200))

    def test_a_record_replayed_under_another_owner_is_credited_to_no_thread(self) -> None:
        full = {'input_tokens': 1, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 3}
        first = self.write('a.jsonl', [claude_row('2026-09-27T14:01:00Z', 'msg-1', 'S1', full)])
        second = self.write('b.jsonl', [claude_row('2026-09-27T14:01:00Z', 'msg-1', 'S2', full, agentId='A7')])
        owners = usage.by_owner([first, second], WINDOW)['owners']
        self.assertEqual(list(owners), [('claude-code', None, None)])

    def test_missing_counts_are_unknown_with_the_known_part_apart(self) -> None:
        partial = {'input_tokens': 5, 'cache_creation_input_tokens': 10, 'output_tokens': 7}
        file = self.write('a.jsonl', [claude_row('2026-09-27T14:01:00Z', 'msg-1', 'S1', partial),
                                      claude_line('2026-09-27T14:02:00Z', 'msg-2', 50)])
        result = usage.file_usage(file, WINDOW)
        self.assertIsNone(result['cachedInput'])
        self.assertEqual(result['knownPartial']['cachedInput'], 1000)
        self.assertEqual(result['unknownRecords'], {'cachedInput': 1, 'reasoningOutputSubset': 1})
        self.assertEqual(result['output'], 57)

    def test_codex_usage_records_count_each_response_once_and_keep_their_turn(self) -> None:
        rows = [codex_record('2026-09-27T14:01:00Z', 'resp-1', 'turn-1', (100, 40, 10, 5)),
                codex_record('2026-09-27T14:02:00Z', 'resp-2', 'turn-2', (300, 200, 0, 9))]
        first, second = self.write('a.jsonl', rows[:1]), self.write('b.jsonl', rows)
        result = usage.by_owner([first, second], WINDOW)
        self.assertEqual((result['records'], result['repeatsDropped']), (2, 1))
        turn = result['owners'][('codex', 'TEST-thread', 'turn-1')]
        self.assertEqual((turn['nonCachedInput'], turn['cacheWriteInput'], turn['cachedInput']), (50, 10, 40))
        self.assertEqual(sum(turn[name] for name in ('nonCachedInput', 'cacheWriteInput', 'cachedInput')), 100)
        self.assertEqual(result['total']['output'], 14)

    def test_codex_cumulative_totals_replayed_into_another_rollout_count_once(self) -> None:
        meta = {'timestamp': '2026-09-27T14:00:00Z', 'type': 'session_meta', 'payload': {'id': 'TEST-thread'}}
        points = [codex_event('2026-09-27T14:01:00Z', 1000, 400, 50, 20),
                  codex_event('2026-09-27T14:02:00Z', 3000, 2000, 150, 60),
                  codex_event('2026-09-27T14:03:00Z', 4000, 2500, 200, 60)]
        first, second = self.write('a.jsonl', [meta, *points[:2]]), self.write('b.jsonl', [meta, *points])
        total = usage.totals(usage.collect([first, second], WINDOW)[0])
        self.assertEqual((total['cachedInput'], total['nonCachedInput'], total['output']), (2500, 1500, 200))

    def test_a_thread_with_response_records_is_never_counted_again_from_cumulative_totals(self) -> None:
        meta = {'timestamp': '2026-09-27T14:00:00Z', 'type': 'session_meta', 'payload': {'id': 'TEST-thread'}}
        old = self.write('old.jsonl', [meta, codex_event('2026-09-27T14:01:00Z', 100, 40, 5, 1)])
        new = self.write('new.jsonl', [codex_record('2026-09-27T14:01:00Z', 'resp-1', 'turn-1', (100, 40, 0, 5))])
        total = usage.totals(usage.collect([old, new], WINDOW)[0])
        self.assertEqual((total['nonCachedInput'], total['cachedInput'], total['output']), (60, 40, 5))

    def test_a_usage_record_without_a_time_is_an_error_not_a_guess(self) -> None:
        row = codex_record('2026-09-27T14:01:00Z', 'resp-1', 'turn-1', (100, 40, 0, 5))
        del row['timestamp']
        with self.assertRaisesRegex(ValueError, 'is not a time'):
            usage.collect([self.write('a.jsonl', [row])], WINDOW)


FULL = {'input_tokens': 5, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 100, 'output_tokens': 7}


def rollout_meta(thread: str, **parent: str) -> dict:
    return {'timestamp': '2026-09-27T14:00:00Z', 'type': 'session_meta', 'payload': {'id': thread, **parent}}


class ForkAndMalformedTests(unittest.TestCase):
    """Forks start from their parent's total; unknowns stay unknown; one bad file never hides the rest."""

    def write(self, name: str, text: str) -> Path:
        directory = getattr(self, 'directory', None) or Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = directory
        (directory / name).write_text(text)
        return directory / name

    def lines(self, name: str, rows: list[dict]) -> Path:
        return self.write(name, ''.join(json.dumps(row) + '\n' for row in rows))

    def token_count(self, stamp: float, totals: tuple[int, int], own: tuple[int, int]) -> dict:
        """A real-shape token_count event: the cumulative (input, output) and the call's own (last_token_usage)."""
        def usage_of(pair: tuple[int, int]) -> dict:
            return {'input_tokens': pair[0], 'cached_input_tokens': 0, 'cache_write_input_tokens': 0,
                    'output_tokens': pair[1], 'reasoning_output_tokens': 0, 'total_tokens': sum(pair)}
        moment = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        return {'timestamp': moment, 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': usage_of(totals), 'last_token_usage': usage_of(own), 'model_context_window': 1}}}

    def test_a_fork_counts_its_own_first_call_over_an_exact_inherited_parent_total(self) -> None:
        """probe_v2.CodexForkRealShape: the fork inherits a parent total recorded after the parent point just
        before the child's first total; its own first call is 48,085."""
        start = WINDOW[0] + 600
        parent = self.lines('parent.jsonl', [rollout_meta('P'),
                                             self.token_count(start - 13, (44_312_445, 90_100), (24_000, 400)),
                                             self.token_count(start + 30, (44_468_500, 90_900), (24_000, 400))])
        fork = self.lines('fork.jsonl', [rollout_meta('F', forked_from_id='P'),
                                         self.token_count(start + 20, (44_516_585, 91_150), (48_085, 250))])
        found = usage.collect_files([parent, fork], (start, start + 100))
        first = [unit for unit in found['units'] if unit.owner[1] == 'F']
        self.assertEqual([(unit.counts['nonCachedInput'], unit.counts['output']) for unit in first], [(48_085, 250)])
        self.assertEqual(found['forksWithoutParentBase'], [])

    def test_a_child_that_starts_fresh_is_counted_from_its_own_first_call(self) -> None:
        child = self.lines('child.jsonl', [rollout_meta('C', parent_thread_id='P2'),
                                           self.token_count(WINDOW[0] + 5, (7_000, 50), (7_000, 50))])
        found = usage.collect_files([child], WINDOW)
        self.assertEqual(([unit.counts['nonCachedInput'] for unit in found['units']], found['forksWithoutParentBase']),
                         ([7_000], []))

    def test_an_inherited_total_the_parent_never_recorded_is_unknown(self) -> None:
        parent = self.lines('parent.jsonl', [rollout_meta('P'),
                                             self.token_count(WINDOW[0] + 10, (100_000, 800), (5_000, 100))])
        fork = self.lines('fork.jsonl', [rollout_meta('F', forked_from_id='P'),
                                         self.token_count(WINDOW[0] + 20, (104_000, 900), (3_000, 100)),
                                         self.token_count(WINDOW[0] + 30, (106_000, 950), (2_000, 50))])
        found = usage.collect_files([parent, fork], WINDOW)
        total = usage.totals([unit for unit in found['units'] if unit.owner[1] == 'F'])
        self.assertEqual((total['nonCachedInput'], total['knownPartial']['nonCachedInput']), (None, 2_000))
        self.assertEqual(found['forksWithoutParentBase'], ['F'])
        alone = usage.collect_files([self.lines('alone.jsonl', [rollout_meta('G', forked_from_id='P9'),
                                                                self.token_count(WINDOW[0] + 5, (9_000, 90),
                                                                                 (1_000, 10))])], WINDOW)
        self.assertIsNone(alone['units'][0].counts['nonCachedInput'])

    def test_codex_records_without_a_response_id_never_merge(self) -> None:
        row = codex_record('2026-09-27T14:01:00Z', 'x', 'turn-1', (10, 0, 0, 5))
        del row['payload']['response_id']
        found = usage.collect_files([self.lines('a.jsonl', [row, row])], WINDOW)
        self.assertEqual((len(found['units']), found['repeatsDropped'], found['recordsWithoutId']), (2, 0, 2))
        self.assertEqual(usage.totals(found['units'])['output'], 10)

    def test_a_compaction_in_the_window_makes_its_thread_partial(self) -> None:
        full = FULL
        compaction = {'type': 'system', 'subtype': 'compact_boundary', 'sessionId': 'S1', 'uuid': 'u-1',
                      'timestamp': '2026-09-27T14:02:00Z'}
        file = self.lines('s.jsonl', [claude_row('2026-09-27T14:01:00Z', 'm1', 'S1', full), compaction])
        found = usage.collect_files([file], WINDOW)
        total = usage.totals(found['units'])
        self.assertEqual((found['compactions'], total['output'], total['knownPartial']['output']), (1, None, 7))

    def test_only_an_unterminated_final_line_is_skipped(self) -> None:
        first = json.dumps(claude_row('2026-09-27T14:01:00Z', 'm1', 'S1', FULL))
        second = json.dumps(claude_row('2026-09-27T14:01:00Z', 'm2', 'S2', FULL))
        live = self.write('live.jsonl', first + '\n{"type": "assi')
        broken = self.write('broken.jsonl', '{"type": "assi\n' + second + '\n')
        found = usage.collect_files([live, broken], WINDOW)
        self.assertEqual((len(found['units']), found['partialFinalLines']), (1, 1))
        self.assertEqual([row['file'] for row in found['unreadable']], [str(broken)])
        self.assertIn('malformed transcript line', found['unreadable'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
