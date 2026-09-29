"""Where a run's (or one output's) elapsed time went, without double counting parallel work.

Every category is an interval union on the batch timeline ``[0, now]``: five launches running
at once count once. Categories may overlap one another (a model span during a media launch);
the report gives each category's union, the union of all of them and their overlap, never a
sum presented as elapsed time. Time outside every category is unattributed, not idle.

Sources, each named in its category:
- the budget authority (``native_budget_waits``): shared preparation, ready-but-no-agent waits
  (claims and releases from the authority trail), media launch windows and repair.
- the merged timing journal (``stage_timing_report.summarize_timings`` over the ``--timing``
  journals; wall times placed on the batch timeline as ``ts - startEpoch``, diagnostics only):
  model and tool spans, host-slot waits (added to ready-but-no-agent), native queue and pressure
  waits, and publication-to-acceptance delays (a publication still awaiting acceptance counts until
  now). A span counts for the run when it carries the batch's run id or sits in a launch's own
  attempt-directory journal inside that launch's window; for one output, when it carries one of
  its task ids or sits in one of its launches' journals inside the window.
- media execution is the launch windows minus the queue and pressure waits attributed as above.
  A launch whose attempt journal was not supplied keeps its waits inside media execution, and the
  category says so (``includesUnattributedQueueTime`` with the launches named).

A category with no interval is unknown, never zero. Journals are diagnostics; nothing here
decides admission, charges or approval.
"""
from __future__ import annotations

from stage_timing_attribution import span_interval, union_seconds
from studio.native_budget_evidence import same_path
from studio.native_budget_waits import authority_intervals, launch_windows
from studio.production.tasks import tasks_of

TIMING = {'model': ('model',), 'tool': ('tool',), 'readyWithoutAgent': ('host-slot-wait',),
          'mediaQueuePressure': ('native-queue-wait', 'pressure-wait')}
CATEGORIES = ('sharedPreparation', 'readyWithoutAgent', 'model', 'tool', 'mediaQueuePressure', 'mediaExecution',
              'repair', 'publishedNotAccepted')
SOURCES = {'sharedPreparation': 'authority: setup and run-scoped planning/specialist/check task claims',
           'readyWithoutAgent': 'authority: AI readiness or release to claim (trail); journal: host-slot-wait spans',
           'model': 'journal: model spans', 'tool': 'journal: tool spans',
           'mediaQueuePressure': 'journal: native-queue-wait and pressure-wait spans',
           'mediaExecution': 'authority: launch admission to outcome, minus the queue/pressure waits attributed '
                             'to the launch',
           'repair': 'authority: repairCycle task claims', 'publishedNotAccepted': 'journal: handoff events'}
SCOPE = ('Each category is a union of intervals on the batch timeline; categories overlap and are never '
         'summed into elapsed time. Unattributed time is not proven idle.')


def merged(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sorted, non-overlapping intervals covering the same time."""
    result: list[list[float]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return [(start, end) for start, end in result]


def _uncovered(interval: tuple[float, float], cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of one interval outside the (merged, sorted) cuts."""
    start, end = interval
    pieces, cursor = [], start
    for low, high in (cut for cut in cuts if cut[1] > start and cut[0] < end):
        if low > cursor:
            pieces.append((cursor, low))
        cursor = max(cursor, high)
    return pieces + ([(cursor, end)] if cursor < end else [])


def subtract(intervals: list[tuple[float, float]], cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of the intervals that no cut covers."""
    removed = merged(cuts)
    return [piece for interval in merged(intervals) for piece in _uncovered(interval, removed)]


def _clip(interval: tuple[float, float], elapsed: float) -> tuple[float, float] | None:
    """The part of an interval inside the batch window, or None."""
    start, end = max(0.0, interval[0]), min(elapsed, interval[1])
    return (start, end) if end > start else None


def _activity(span: dict) -> str | None:
    """A span's declared activity."""
    metadata = span.get('metadata')
    return metadata.get('activity') if isinstance(metadata, dict) else None


def _located(span: dict, interval: tuple[float, float], windows: list[dict]) -> bool:
    """The span sits in a launch's own attempt journal and inside that launch's window."""
    folder = span.get('journalDir')
    return isinstance(folder, str) and any(
        same_path(folder, window['directory']) and interval[0] < window['end'] and interval[1] > window['start']
        for window in windows)


def journal_intervals(record: dict, timing: dict, scope: dict, elapsed: float) -> dict:
    """Journal spans and handoff delays attributed to the scope, on the batch timeline."""
    run, start, rows = record['batchId'], record['startEpoch'], {name: [] for name in (*TIMING, 'publishedNotAccepted')}
    mine = (lambda row: row.get('taskId') in scope['tasks']) if scope['clipId'] \
        else (lambda row: row.get('runId') == run)
    category = {activity: name for name, activities in TIMING.items() for activity in activities}
    for span in timing['spans']:
        interval = span_interval(span) if _activity(span) in category else None
        placed = (interval[0] - start, interval[1] - start) if interval else None
        if placed and (mine(span) or _located(span, placed, scope['windows'])):
            rows[category[_activity(span)]].append(placed)
    for item in timing['handoffs']['publications']:
        if item['runId'] != run or not mine(item) and scope['clipId']:
            continue
        ends = [row['acceptedAt'] - start for row in item['acceptances'] if row['delaySeconds'] is not None]
        ends = ends or ([] if item['acceptances'] else [elapsed])
        rows['publishedNotAccepted'].extend((item['publishedAt'] - start, end) for end in ends)
    return rows


def _unjournaled(scope: dict, timing: dict | None) -> list[str]:
    """Launches whose own attempt journal was not supplied: their waits stay inside media execution."""
    folders = (timing or {}).get('journalDirs') or []
    return [window['attemptId'] for window in scope['windows']
            if not any(same_path(folder, window['directory']) for folder in folders)]


def _category(name: str, intervals: list, reason: str | None) -> dict:
    """One category's union, or unknown when nothing was observed."""
    if not intervals:
        return {'status': 'unknown', 'unionSeconds': None, 'intervals': 0, 'source': SOURCES[name],
                'reason': reason or 'no interval of this kind was recorded'}
    return {'status': 'measured', 'unionSeconds': round(union_seconds(intervals), 3), 'intervals': len(intervals),
            'source': SOURCES[name]}


def _scope(record: dict, clip_id: str | None, events: tuple[dict, ...], elapsed: float) -> dict:
    """The tasks, launch windows and trail events one breakdown covers."""
    tasks = tasks_of(record)
    attempts = [(key, row) for key, clip in record['clips'].items() if clip_id in (None, key)
                for row in clip['attempts']]
    return {'clipId': clip_id, 'events': events, 'windows': launch_windows(attempts, elapsed),
            'tasks': {task_id for task_id, task in tasks.items() if clip_id is None or task['clipId'] == clip_id}}


def _categories(clipped: dict, timing: dict | None, scope: dict) -> dict:
    """Every category's union, reason and source; media execution names launches with unattributed waits."""
    missing = None if timing is not None else 'no timing journal was supplied (status --timing)'
    categories = {name: _category(name, clipped[name], missing if name in (*TIMING, 'publishedNotAccepted')
                                  and name != 'readyWithoutAgent' else None) for name in CATEGORIES}
    unjournaled = _unjournaled(scope, timing)
    categories['mediaExecution'].update(launches=len(scope['windows']), includesUnattributedQueueTime=bool(unjournaled))
    if not unjournaled:
        return categories
    note = (f'{len(unjournaled)} launch(es) have no supplied attempt journal, so their pool and pressure waits '
            f'are counted as media execution: {", ".join(unjournaled[:8])}')
    queue = categories['mediaQueuePressure']
    categories['mediaExecution']['unattributedQueueTime'] = queue['unattributedQueueTime'] = note
    if queue['status'] == 'unknown' and timing is not None:   # without a journal the reason already says so
        queue['reason'] = f'queue time may exist but is not attributed: {note}'
    return categories


def breakdown(record: dict, elapsed: float, timing: dict | None, scope_of: tuple = (None, ())) -> dict:
    """The elapsed-time breakdown of the run, or of one output. scope_of = (clip id or None, trail events)."""
    clip_id, events = scope_of
    scope = _scope(record, clip_id, events, elapsed)
    found = authority_intervals(record, scope, elapsed)
    rows = {name: list(found['rows'].get(name, [])) for name in CATEGORIES}
    rows['mediaExecution'] = [(window['start'], window['end']) for window in scope['windows']]
    if timing is not None:
        for name, values in journal_intervals(record, timing, scope, elapsed).items():
            rows[name].extend(values)
    rows['mediaExecution'] = subtract(rows['mediaExecution'], rows['mediaQueuePressure'])
    clipped = {name: [item for item in (_clip(row, elapsed) for row in values) if item]
               for name, values in rows.items()}
    categories = _categories(clipped, timing, scope)
    union = union_seconds([item for values in clipped.values() for item in values])
    summed = sum(row['unionSeconds'] or 0.0 for row in categories.values())
    return {'scope': clip_id or 'run', 'elapsedSeconds': round(elapsed, 3), 'categories': categories,
            'categorizedUnionSeconds': round(union, 3), 'categorySumSeconds': round(summed, 3),
            'concurrentOverlapSeconds': round(max(0.0, summed - union), 3),
            'unattributedSeconds': round(max(0.0, elapsed - union), 3),
            'untimedReadyWaits': found['untimedReadyWaits'], 'timingJournal': timing is not None, 'note': SCOPE}
