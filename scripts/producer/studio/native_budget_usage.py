"""AI reservations and host-reported token usage, linked to tasks by run, task and host identity.

Reservations are the authority's own counts: per output, the dispatch counters against their
limits and the charged AI tasks; per run, host slots, run reservations and charges. Charges are
never refunded, so these only grow.

Usage has two sources, reported side by side and never added together:
- authority: each charged AI task's cumulative host report (``production.callbacks.record_usage``
  merges replays field-wise, so a replay never raises a count). Tasks naming the same exact host
  turn, or the same process, are one execution, counted once (field-wise maximum). A host handle
  without a turn identifies no turn, so each such task is its own execution.
- transcripts (``status --transcript``): ``agent_usage`` records from the batch start to now,
  each message or response once across files, linked to a task through its host handle: host,
  thread and turn where the transcript records turns (Codex ``token_usage_record``), else host and
  thread (a thread's turn-linked records are not counted again at thread level). A thread linked
  to tasks of several outputs is reported at run level only. The run totals cover every record,
  linked or not, with the unlinked ones in their own bucket.

Missing usage is unknown, never zero: a total is null unless every counted execution reported the
field (``knownPartial`` keeps the known part); it is also null while any record is unlinked, a
host task has no record, a transcript was unreadable or a compaction's usage is missing, and when
no execution was observed at all. AI dispatches admitted without a task row (``native_batch.py
admit``) have no report, so they make the authority totals unknown. Cached input is part of input
and reasoning part of output; neither is added again. Token counters are not credits.
"""
from __future__ import annotations

from agent_usage import NOTE, totals
from studio.native_budget_schema import DISPATCH_KINDS
from studio.production.host_contract import USAGE_FIELDS
from studio.production.task_schema import holds_slot, is_ai
from studio.production.tasks import active_ai, tasks_of

UNKNOWN = dict.fromkeys(USAGE_FIELDS)


def _execution(task: dict) -> tuple:
    """The exact execution a task's usage belongs to: its host turn, its process, or the task itself."""
    handle = task['handle']
    if handle is None or handle['type'] == 'host' and handle['turn'] is None:
        return ('task', task['id'])
    if handle['type'] == 'host':
        return ('host', handle['host'], handle['thread'], handle['turn'])
    return ('process', handle['pid'], handle['pgid'], handle['started'])


def _largest(reports: list[dict]) -> dict | None:
    """Field-wise maximum of cumulative reports of one execution; None when none was reported."""
    if not reports:
        return None
    return {name: max((row[name] for row in reports if row[name] is not None), default=None) for name in USAGE_FIELDS}


def _sums(rows: list[dict | None], unknown_because: list[str]) -> dict:
    """Totals that are null while any execution lacks the field, a named reason holds, or nothing was observed."""
    known = {name: sum(row[name] for row in rows if row and row[name] is not None) for name in USAGE_FIELDS}
    unknown = {name: sum(1 for row in rows if not row or row[name] is None) for name in USAGE_FIELDS}
    reasons = [*unknown_because, *([] if rows else ['no execution was observed'])]
    return {'totals': dict(UNKNOWN) if reasons else {name: None if unknown[name] else known[name]
                                                     for name in USAGE_FIELDS},
            'knownPartial': known, 'unknownExecutions': {name: count for name, count in unknown.items() if count},
            'unknownBecause': reasons}


def authority_usage(tasks: list[dict], untracked: int = 0) -> dict:
    """Charged AI tasks' reports, one per exact execution."""
    groups: dict[tuple, list[dict]] = {}
    for task in tasks:
        groups.setdefault(_execution(task), []).append(task)
    usage = [_largest([task['usage'] for task in rows if task['usage']]) for rows in groups.values()]
    because = [f'{untracked} AI dispatch(es) were admitted without a task and report no usage'] if untracked else []
    return {'executions': len(groups), 'reported': sum(row is not None for row in usage),
            'tasksSharingAnExecution': len(tasks) - len(groups), **_sums(usage, because)}


def normalized(counts: dict) -> dict:
    """agent_usage counters in the host contract's fields (input includes its cached and cache-write parts)."""
    parts = (counts['nonCachedInput'], counts['cacheWriteInput'], counts['cachedInput'])
    return {'inputTokens': None if None in parts else sum(parts), 'cachedInputTokens': counts['cachedInput'],
            'outputTokens': counts['output'], 'reasoningTokens': counts['reasoningOutputSubset']}


def transcript_links(units: list, tasks: list[dict]) -> dict:
    """Each transcript link key (host, thread, turn or '*') with its tasks, outputs and records."""
    turned = {unit.owner for unit in units if unit.owner[1] is not None and unit.owner[2] is not None}
    links: dict[tuple, dict] = {}
    for task in tasks:
        handle = task['handle']
        if handle is None or handle['type'] != 'host':
            continue
        exact = (handle['host'], handle['thread'], handle['turn'])
        key = exact if exact in turned else (handle['host'], handle['thread'], '*')
        link = links.setdefault(key, {'tasks': [], 'clips': set(), 'units': []})
        link['tasks'].append(task['id'])
        link['clips'].add(task['clipId'])
    claimed = {key for key in links if key[2] != '*'}
    for unit in units:
        key = unit.owner if unit.owner in claimed else (*unit.owner[:2], '*')
        if key in links:
            links[key]['units'].append(unit)
    return links


def _link_row(key: tuple, link: dict) -> dict:
    """One link: whose records, how many and their totals in host-contract fields."""
    return {'host': key[0], 'thread': key[1], 'turn': None if key[2] == '*' else key[2],
            'level': 'thread' if key[2] == '*' else 'turn', 'tasks': sorted(link['tasks']),
            'records': len(link['units']), 'usage': normalized(totals(link['units']))}


def _bucket(units: list) -> dict:
    """Records' totals in host-contract fields (the known part kept apart)."""
    counted = totals(units)
    return {'records': len(units), **normalized(counted), 'knownPartial': normalized(counted['knownPartial'])}


def _record_totals(units: list, reasons: list[str]) -> dict:
    """Transcript totals: null while any reason holds or no record was observed; the known part kept apart."""
    reasons = [*reasons, *([] if units else ['no transcript record was observed'])]
    counted = totals(units)
    shown = normalized(counted)
    return {'totals': dict(UNKNOWN) if reasons else shown, 'knownPartial': normalized(counted['knownPartial']),
            'unknownFields': [name for name, value in shown.items() if value is None], 'unknownBecause': reasons}


def _reasons(transcripts: dict, links: dict, scope: tuple[list[dict], int]) -> list[str]:
    """Why a transcript total cannot be complete for this scope."""
    host_tasks, unlinked = scope
    linked = {task_id for link in links.values() if link['units'] for task_id in link['tasks']}
    missing = [task['id'] for task in host_tasks if task['id'] not in linked]
    return [*([f'{len(missing)} host task(s) have no transcript record'] if missing else []),
            *([f'{unlinked} record(s) name no task of this run'] if unlinked else []),
            *([f'{len(transcripts["unreadable"])} transcript(s) were unreadable'] if transcripts['unreadable'] else []),
            *([f'{len(transcripts["forksWithoutParentBase"])} fork(s) lack their parent total']
              if transcripts['forksWithoutParentBase'] else [])]


def transcript_usage(transcripts: dict | None, tasks: list[dict], clip_id: str | None) -> dict:
    """Transcript records linked to the run's charged AI tasks; for one output, only links wholly its own."""
    if transcripts is None:
        return {'status': 'not-supplied', 'reason': 'no host transcript was supplied (status --transcript)'}
    links = transcript_links(transcripts['units'], tasks)
    shared = {key for key, link in links.items() if len(link['clips']) > 1}
    kept = {key: link for key, link in links.items() if clip_id is None or link['clips'] == {clip_id}}
    rows = [_link_row(key, link) for key, link in sorted(kept.items(), key=lambda item: str(item[0]))]
    scoped = [task for task in tasks if clip_id is None or task['clipId'] == clip_id]
    host_tasks = [task for task in scoped if task['handle'] and task['handle']['type'] == 'host']
    mine = {id(unit) for link in links.values() for unit in link['units']}
    unlinked = [unit for unit in transcripts['units'] if id(unit) not in mine]
    excluded = sorted(str(key) for key in shared if clip_id in links[key]['clips']) if clip_id else []
    reasons = _reasons(transcripts, kept, (host_tasks, len(unlinked) if clip_id is None else 0))
    reasons += [f'{len(excluded)} thread(s) are shared with other outputs'] if excluded else []
    counted = [unit for key in kept for unit in links[key]['units']] + (unlinked if clip_id is None else [])
    result = {'status': 'linked', 'links': rows, **_record_totals(counted, reasons),
              'linked': _bucket([unit for key in kept for unit in links[key]['units']]),
              'hostTasks': len(host_tasks), 'tasksWithoutHostHandle': len(scoped) - len(host_tasks)}
    if clip_id is not None:
        return {**result, 'sharedAcrossOutputsExcluded': excluded}
    return {**result, 'unlinked': _bucket(unlinked), 'sharedAcrossOutputs': sorted(map(str, shared)),
            **{key: transcripts[key] for key in ('repeatsDropped', 'unreadable', 'partialFinalLines',
                                                 'forksWithoutParentBase', 'recordsWithoutId', 'compactions')}}


def untracked_dispatches(record: dict, clip_id: str | None) -> int:
    """AI dispatches admitted without a task row (``native_batch.py admit``): their usage is unknown."""
    clips = [clip_id] if clip_id is not None else list(record['clips'])
    admitted = sum(len(record['clips'][key]['dispatches']) for key in clips)
    tasked = sum(1 for task in tasks_of(record).values()
                 if task['charged'] and task['kind'] in DISPATCH_KINDS and task['clipId'] in clips)
    return max(0, admitted - tasked)


def ai_usage(record: dict, clip_id: str | None, transcripts: dict | None) -> dict:
    """Reservations and usage coverage for one output, or for the run when clip_id is None."""
    charged = [task for task in tasks_of(record).values() if is_ai(task) and task['charged']]
    tasks = [task for task in charged if clip_id is None or task['clipId'] == clip_id]
    untracked = untracked_dispatches(record, clip_id)
    authority = authority_usage(tasks, untracked)
    coverage = {'chargedAiTasks': len(tasks), 'tasksWithAuthorityUsage': sum(1 for task in tasks if task['usage']),
                'untrackedDispatches': untracked, 'complete': not authority['unknownBecause']
                and not authority['unknownExecutions']}
    return {'reservations': reservations(record, clip_id), 'usage': {
        'coverage': coverage, 'authority': authority,
        'transcripts': transcript_usage(transcripts, charged, clip_id), 'note': NOTE}}


def reservations(record: dict, clip_id: str | None) -> dict:
    """The authority's AI charges: per output its dispatch counters, per run its slots and reservations."""
    tasks = [task for task in tasks_of(record).values() if is_ai(task)]
    if clip_id is not None:
        clip, limits = record['clips'][clip_id], record['limits']
        mine = [task for task in tasks if task['clipId'] == clip_id]
        return {'dispatchCounters': {kind: f"{clip['counters'][kind]}/{limits[kind]}" for kind in DISPATCH_KINDS},
                'chargedTasks': sum(task['charged'] for task in mine),
                'holdingSlots': sum(holds_slot(task) for task in mine)}
    ai = record['production']['ai']
    return {'slots': ai['slots'], 'activeSlots': active_ai(record), 'runReservations': ai['reservations'],
            'charged': ai['charged'], 'readyAiTasks': sum(task['state'] == 'ready' for task in tasks)}
