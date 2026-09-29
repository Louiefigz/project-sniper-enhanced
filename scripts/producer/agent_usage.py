#!/usr/bin/env python3
"""Per-agent token counters for a production window, read from the host's own transcripts.

Reads Claude Code transcripts (one JSONL per session or subagent; usage per assistant message)
and Codex rollouts (``agent_usage_codex``: per-response ``token_usage_record`` rows, or cumulative
``token_count`` events in older rollouts, forks based on their parent). Nothing is sent anywhere.
The counters are what the host reported; they are token counters, not credits, a bill or a
subscription percentage.

Accounting rules (so nothing is double-counted and nothing unknown reads as zero):
- A usage record is counted once by its identity: a Claude message id, a Codex response id, or a
  Codex cumulative point. A record repeated on several content-block lines, or replayed into
  another file by a resumed or forked session, is one record (field-wise maximum); replayed under
  another owner it is credited to no thread. A Codex record without a response id is never merged.
- Cached input is a subset of input and reasoning output a subset of output;
  ``nonCachedInput + cacheWriteInput + cachedInput`` is the whole input.
- A count the host did not report is unknown (null), never zero; a sum with an unknown part is
  unknown, and ``knownPartial`` keeps the known part apart. A Claude ``compact_boundary`` inside the
  window is a model call whose usage the transcript omits: it adds an unknown record to its thread.
- One malformed transcript is reported by name and leaves the others readable; only a live
  transcript's unterminated final line (still being written) is skipped and counted.

Each record carries its owner: host, thread (Claude ``agentId`` for a subagent transcript, else
``sessionId``; Codex ``thread_id``) and, where the host records it, turn (Codex ``turn_id``;
Claude transcripts carry none).

  agent_usage.py --since 2026-09-27T14:00:00Z [--until ...] FILE [FILE ...]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import agent_usage_codex as codex
from agent_usage_codex import count

FIELDS = ('nonCachedInput', 'cacheWriteInput', 'cachedInput', 'output', 'reasoningOutputSubset')
NOTE = 'Host-reported token counters; not credits, a bill or a subscription percentage.'
CODEX_TYPES = ('event_msg', 'session_meta', 'token_usage_record')


@dataclass(frozen=True)
class Unit:
    """One host usage record: dedupe key, owner (host, thread, turn), time and counts (None = unknown)."""

    key: tuple
    owner: tuple
    stamp: float
    counts: dict


def parse_time(value: object) -> float:
    """ISO-8601 (with Z) or epoch seconds; anything else is a ValueError."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f'usage record time {value!r} is not a time')
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def read_rows(file: Path) -> tuple[list[dict], int]:
    """Every JSON line and whether an unterminated final line was skipped (1) or not (0).

    A malformed complete line is an error, not silently skipped.
    """
    text = file.read_text()
    lines = text.split('\n')
    partial = lines.pop() if lines else ''
    rows = [_row(file, number, line) for number, line in enumerate(lines, 1) if line.strip()]
    if not partial.strip():
        return rows, 0
    try:
        rows.append(json.loads(partial))
    except ValueError:
        return rows, 1
    return rows, 0


def _row(file: Path, number: int, line: str) -> dict:
    """Parse one transcript line."""
    try:
        return json.loads(line)
    except ValueError as error:
        raise ValueError(f'{file}:{number}: malformed transcript line') from error


def _claude_counts(usage: dict) -> dict:
    """agent_usage fields from one Claude message usage object."""
    details = usage.get('output_tokens_details') if isinstance(usage.get('output_tokens_details'), dict) else {}
    return {'nonCachedInput': count(usage.get('input_tokens')),
            'cacheWriteInput': count(usage.get('cache_creation_input_tokens')),
            'cachedInput': count(usage.get('cache_read_input_tokens')), 'output': count(usage.get('output_tokens')),
            'reasoningOutputSubset': count(details.get('thinking_tokens'))}


def _compaction(row: dict) -> Unit | None:
    """A compact_boundary: the compaction call's usage is not in the transcript, so it is unknown."""
    if row.get('type') != 'system' or row.get('subtype') != 'compact_boundary' or not row.get('timestamp'):
        return None
    thread = row.get('agentId') or row.get('sessionId')
    key = ('claude-compaction', row.get('uuid') or f'{thread}@{row["timestamp"]}')
    return Unit(key, ('claude-code', thread, None), parse_time(row['timestamp']),
                {**dict.fromkeys(FIELDS), 'compaction': True})


def claude_units(rows: list[dict]) -> list[Unit]:
    """One unit per assistant message line with usage (its id deduplicates block lines and replays),
    and an unknown unit per compaction."""
    units = []
    for row in rows:
        message = row.get('message') if isinstance(row.get('message'), dict) else {}
        usage, stamp = message.get('usage'), row.get('timestamp')
        compaction = _compaction(row)
        if compaction is not None:
            units.append(compaction)
        if row.get('type') != 'assistant' or not isinstance(usage, dict) or not stamp or not message.get('id'):
            continue
        thread = row.get('agentId') or row.get('sessionId')
        units.append(Unit(('claude-code', message['id']), ('claude-code', thread, None), parse_time(stamp),
                          _claude_counts(usage)))
    return units


def file_units(file: Path) -> dict:
    """One transcript: its host, records, cumulative points by thread and skipped partial line."""
    rows, partial = read_rows(file)
    if not any(row.get('type') in CODEX_TYPES for row in rows):
        return {'host': 'claude-code', 'units': claude_units(rows), 'threads': {}, 'partial': partial}
    records = [Unit(key, owner, parse_time(stamp), counts) for key, owner, stamp, counts in codex.record_rows(rows)]
    thread = codex.rollout_thread(rows, f'file:{file}')
    points = [] if records else [(parse_time(stamp), total, last)
                                 for stamp, total, last in codex.cumulative_points(rows)]
    return {'host': 'codex', 'units': records, 'threads': {thread: points} if points else {}, 'partial': partial}


def merge(units: list[Unit]) -> tuple[dict, int]:
    """One unit per key (field-wise maximum of repeats) and how many repeats were dropped.

    A record repeated under a different owner (a replay into another session) is counted once
    and owned by no thread, so it is never credited to either task.
    """
    merged: dict[tuple, Unit] = {}
    for unit in units:
        known = merged.get(unit.key)
        if known is None:
            merged[unit.key] = unit
            continue
        counts = {name: max((value for value in (known.counts.get(name), unit.counts.get(name)) if value is not None),
                            default=None) for name in FIELDS}
        owner = known.owner if known.owner == unit.owner else (known.owner[0], None, None)
        merged[unit.key] = Unit(unit.key, owner, min(known.stamp, unit.stamp), {**known.counts, **counts})
    return merged, len(units) - len(merged)


def _cumulative(threads: dict, recorded: set) -> tuple[list[Unit], list[str]]:
    """Units of every cumulative-only thread (forks based on their parent), and forks without a parent base."""
    points = {}
    for thread, rows in threads.items():
        points.setdefault(thread.thread, []).extend(rows)
    parents: dict[str, str | None] = {}
    for thread in threads:
        parents[thread.thread] = parents.get(thread.thread) or thread.parent
    units, unbased = [], []
    for name, rows in points.items():
        if name in recorded:  # a thread with per-response records is counted from those records only
            continue
        ordered, parent = codex.unique_points(rows), parents.get(name)
        base = {} if parent is None else codex.fork_base(ordered, codex.unique_points(points.get(parent, [])))[0]
        unbased += [name] if base is None else []
        units += [Unit(('codex-cumulative', name, point[0], json.dumps(point[1], sort_keys=True)),
                       ('codex', name, None), point[0], {**counts, 'segmentStart': start})
                  for point, (_stamp, counts, start) in zip(ordered, codex.increases(ordered, base))]
    return units, unbased


def collect_files(files: list[Path], window: tuple[float, float]) -> dict:
    """Every distinct record inside the window; an unreadable file is named and the others still count."""
    units, threads, unreadable, partial = [], {}, [], 0
    for file in files:
        try:
            found = file_units(file)
        except (OSError, UnicodeError, ValueError) as error:
            unreadable.append({'file': str(file), 'reason': f'{type(error).__name__}: {error}'[:300]})
            continue
        units.extend(found['units'])
        partial += found['partial']
        for thread, rows in found['threads'].items():
            threads.setdefault(thread, []).extend(rows)
    cumulative, unbased = _cumulative(threads, {unit.owner[1] for unit in units if unit.owner[0] == 'codex'})
    merged, repeats = merge(units + cumulative)
    inside = [unit for unit in merged.values() if window[0] <= unit.stamp <= window[1]]
    return {'units': inside, 'repeatsDropped': repeats, 'unreadable': unreadable, 'partialFinalLines': partial,
            'forksWithoutParentBase': sorted(unbased),
            'recordsWithoutId': sum(1 for unit in inside if unit.counts.get('unkeyed')),
            'compactions': sum(1 for unit in inside if unit.counts.get('compaction'))}


def collect(files: list[Path], window: tuple[float, float]) -> tuple[list[Unit], int]:
    """``collect_files`` for a caller that needs every file readable: the first unreadable one raises."""
    found = collect_files(files, window)
    if found['unreadable']:
        raise ValueError(found['unreadable'][0]['reason'])
    return found['units'], found['repeatsDropped']


def totals(units: list[Unit]) -> dict:
    """Per-field sums; a field any unit did not report is unknown, with its known part kept apart."""
    known = {name: sum(unit.counts[name] for unit in units if unit.counts.get(name) is not None) for name in FIELDS}
    unknown = {name: sum(1 for unit in units if unit.counts.get(name) is None) for name in FIELDS}
    return {**{name: None if unknown[name] else known[name] for name in FIELDS},
            'knownPartial': known, 'unknownRecords': {name: number for name, number in unknown.items() if number}}


def file_usage(file: Path, window: tuple[float, float]) -> dict:
    """One transcript's own counters (duplicates inside the file counted once)."""
    units, _repeats = collect([file], window)
    host = file_units(file)['host']
    extra = {'segments': sum(bool(unit.counts.get('segmentStart')) for unit in units)} if host == 'codex' \
        else {'messages': sum(1 for unit in units if not unit.counts.get('compaction'))}
    return {'file': str(file), 'host': host, 'records': len(units), **extra, **totals(units)}


def by_owner(files: list[Path], window: tuple[float, float]) -> dict:
    """Counters per (host, thread, turn) owner across files, each record once, and the repeats dropped."""
    units, replays = collect(files, window)
    owners: dict[tuple, list[Unit]] = {}
    for unit in units:
        owners.setdefault(unit.owner, []).append(unit)
    return {'owners': {owner: {'records': len(rows), **totals(rows)} for owner, rows in owners.items()},
            'records': len(units), 'repeatsDropped': replays, 'total': totals(units)}


def main() -> None:
    """Print per-file counters and their deduplicated sum for one time window."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--since', required=True)
    parser.add_argument('--until')
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    window = (parse_time(args.since), parse_time(args.until) if args.until else float('inf'))
    found = collect_files(args.files, window)
    readable = [file for file in args.files if str(file) not in {row['file'] for row in found['unreadable']}]
    print(json.dumps({'window': {'since': args.since, 'until': args.until},
                      'agents': [file_usage(file, window) for file in readable], 'total': totals(found['units']),
                      **{key: value for key, value in found.items() if key != 'units'}, 'note': NOTE}, indent=2))


if __name__ == '__main__':
    main()
