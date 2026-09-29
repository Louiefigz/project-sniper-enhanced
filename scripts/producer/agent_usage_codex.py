"""Codex rollout usage for ``agent_usage``: per-response records and cumulative totals, forks included.

- ``token_usage_record`` rows are per-response usage, keyed by ``response_id`` and owned by their
  ``thread_id``/``turn_id``. A record without a response id is never merged with anything (two
  distinct responses can report the same second and counts); it is counted and flagged ``unkeyed``.
- Older rollouts carry only cumulative ``token_count`` totals (and each event's own call usage,
  ``last_token_usage``). A rollout whose ``session_meta`` names ``forked_from_id`` or
  ``parent_thread_id`` may start from its parent's history, so its first total can include what it
  inherited: that is the first total minus the first call's own usage. It is accepted only when it
  is zero (the child starts fresh) or equals a total the parent recorded exactly; otherwise the
  first increase is unknown (never counted whole, never guessed from a nearby parent total).
- Codex input includes its cached and cache-write parts; reasoning is part of output.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass

CODEX_KEYS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens',
              'reasoning_output_tokens')
PARENT_KEYS = ('forked_from_id', 'parent_thread_id')
_UNKEYED = itertools.count()  # every id-less record gets its own key


@dataclass(frozen=True)
class Thread:
    """One rollout's thread identity and the parent it was forked or spawned from (None for a root)."""

    thread: str
    parent: str | None


def count(value: object) -> int | None:
    """A reported nonnegative integer count, else unknown."""
    return value if type(value) is int and value >= 0 else None


def _minus(total: int | None, *parts: int | None) -> int | None:
    """total minus known parts; unknown when any part is unknown."""
    if total is None or any(part is None for part in parts):
        return None
    return total - sum(parts)


def codex_counts(usage: dict) -> dict:
    """agent_usage fields from one Codex usage object."""
    total, cached, written = (count(usage.get(key)) for key in CODEX_KEYS[:3])
    return {'nonCachedInput': _minus(total, cached, written), 'cacheWriteInput': written, 'cachedInput': cached,
            'output': count(usage.get('output_tokens')),
            'reasoningOutputSubset': count(usage.get('reasoning_output_tokens'))}


def _payload(row: dict) -> dict:
    """A row's payload object, or an empty one."""
    return row['payload'] if isinstance(row.get('payload'), dict) else {}


def rollout_thread(rows: list[dict], fallback: str) -> Thread:
    """The rollout's thread (its session_meta id) and the parent it was forked or spawned from."""
    for row in rows:
        payload = _payload(row)
        if row.get('type') == 'session_meta' and isinstance(payload.get('id'), str):
            parent = next((payload[key] for key in PARENT_KEYS if isinstance(payload.get(key), str) and payload[key]),
                          None)
            return Thread(payload['id'], parent)
    return Thread(fallback, None)


def record_rows(rows: list[dict]) -> list[tuple[tuple, tuple, object, dict]]:
    """(key, owner, time, counts) of every per-response record; an id-less record gets a unique key."""
    found = []
    for row in rows:
        payload = _payload(row)
        if row.get('type') != 'token_usage_record' or not isinstance(payload.get('usage'), dict):
            continue
        response = payload.get('response_id')
        keyed = isinstance(response, str) and bool(response)
        key = ('codex', response) if keyed else ('codex-unkeyed', next(_UNKEYED))
        counts = {**codex_counts(payload['usage']), **({} if keyed else {'unkeyed': True})}
        found.append((key, ('codex', payload.get('thread_id'), payload.get('turn_id')), row.get('timestamp'), counts))
    return found


def cumulative_points(rows: list[dict]) -> list[tuple[object, dict, dict | None]]:
    """(time, total, last) of every token_count event: its cumulative total and its own call's usage."""
    points = []
    for row in rows:
        payload = _payload(row)
        info = payload.get('info') if isinstance(payload.get('info'), dict) else {}
        if row.get('type') == 'event_msg' and payload.get('type') == 'token_count' \
                and isinstance(info.get('total_token_usage'), dict):
            last = info.get('last_token_usage') if isinstance(info.get('last_token_usage'), dict) else None
            points.append((row.get('timestamp'), info['total_token_usage'], last))
    return points


def _delta(total: dict, base: dict) -> dict:
    """One cumulative total's increase over its base (an empty base: the whole total); unknown stays unknown."""
    delta = {}
    for key in CODEX_KEYS:
        now, before = count(total.get(key)), count(base.get(key)) if base else 0
        delta[key] = None if now is None or before is None else now - before
    return delta


def _input(total: dict) -> int:
    """The reported cumulative input, 0 when unknown (orders and detects resets only)."""
    return count(total.get('input_tokens')) or 0


def unique_points(points: list[tuple]) -> list[tuple[float, dict, dict | None]]:
    """Chronological (time, total, last) points with exact replays (same time and totals) removed."""
    unique = {(point[0], json.dumps(point[1], sort_keys=True)): point for point in points}
    return sorted(unique.values(), key=lambda item: (item[0], _input(item[1])))


def _vector(usage: dict) -> tuple[int, ...]:
    """One usage object's counts in CODEX_KEYS order (an absent count as 0, for exact comparison only)."""
    return tuple(count(usage.get(key)) or 0 for key in CODEX_KEYS)


def fork_base(child: list[tuple], parent: list[tuple] | None) -> tuple[dict | None, str]:
    """The base of a forked or spawned child's first increase, and how it was established.

    The child's first total is what it inherited plus its own first call (``last_token_usage``).
    What it inherited is accepted only when it is zero (a child that starts fresh) or equals a total
    the parent actually recorded; anything else, a missing call usage included, leaves it unknown.
    """
    if not child or not isinstance(child[0][2], dict):
        return None, 'no-first-call-usage'
    inherited = tuple(total - own for total, own in zip(_vector(child[0][1]), _vector(child[0][2])))
    if not any(inherited):
        return {}, 'starts-fresh'
    match = next((point[1] for point in parent or [] if _vector(point[1]) == inherited), None)
    return (match, 'exact-parent-total') if match is not None else (None, 'no-exact-parent-total')


def increases(points: list[tuple], base: dict | None) -> list[tuple[float, dict, bool]]:
    """(time, counts, segmentStart) per total. ``base``: {} for a root thread or a child that starts fresh,
    the exact inherited parent total for a fork, None when the inherited part is not established (the
    first increase is unknown)."""
    rows, previous = [], None
    for index, (stamp, total, _last) in enumerate(points):
        reset = previous is not None and _input(total) < _input(previous)
        if index == 0 and base is None:
            counts = dict.fromkeys(codex_counts({}), None)
        else:
            counts = codex_counts(_delta(total, {} if reset else (previous if previous is not None else base)))
        rows.append((stamp, counts, index == 0 or reset))
        previous = total
    return rows
