"""Queue-aware launch forecasts that decide whether work still fits the deadline.

Rates are seconds of wall time per second of authored output plus a fixed part, measured one at a
time on the integrated engine and scaled by the qualified pool's measured three-way slowdown
(``native_budget_schema.PROVISIONAL_RATES`` names the evidence). The safety factor covers variance.
A forecast only decides admission; it never extends a deadline, and it never assumes a duration it
was not given. Each launch is forecast with its own output's format rates and deadlines
(``production.formats``): a Long launch at the Long rates, a Short's at today's Short rates.
"""
from __future__ import annotations

import math
from functools import lru_cache

from studio.production.formats import clip_deadlines, clip_rates, output_format

ROUTE_RATE = {'preview': 'preview', 'final': 'final', 'draft': 'draft', 'verify': 'verify',
              'resume': 'verify', 'promote': 'promote'}


def route_seconds(rates: dict, route: str, output_seconds: float,
                  window_seconds: float | tuple[float | None, int] | None = None) -> float:
    """Forecast one launch's own execution time, including the safety factor.

    A rate with ``perWindowSecond`` (a Long's moving preview) adds that picture over its windows: the preview
    packet's summed ``window_seconds`` when given, else the whole program (a bound).
    """
    if type(output_seconds) not in (int, float) or not 0 < output_seconds <= 3600:
        raise ValueError('A forecast needs the launch\'s known authored duration')
    windows, members = window_seconds if type(window_seconds) is tuple else (window_seconds, 1)
    if type(members) is not int or not 1 <= members <= 4:
        raise ValueError('Preview family has one to four frozen members')
    rate = rates['routes'][ROUTE_RATE[route]]
    grouped = members > 1
    if grouped and (route not in ('preview', 'final') or 'perWindowSecond' not in rates['routes']['preview']):
        raise ValueError('Only Long preview/final families support grouped work')
    windows = output_seconds if windows is None else windows
    if type(windows) not in (int, float) or not 0 <= windows <= output_seconds * (2 if members > 1 else 1):
        raise ValueError('Preview window seconds lie within the program')
    picture = rate['perWindowSecond'] * windows if 'perWindowSecond' in rate else 0.0
    source_factor = 2 if grouped and route == 'final' else members
    value = (rate['perOutputSecond'] * output_seconds * source_factor + rate['fixedSeconds'] * members + picture) \
        * rates['safetyFactor']
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid launch forecast')
    return value


def queue_occupants(record: dict, attempts: list | None = None) -> list[tuple[float, float | None, float, float]]:
    """(admitted, completed, forecast duration, grant end) of every launch that shapes the queue.

    That is every running launch (the clip's own included: a preview beside its draft holds a
    slot) and every launch that ran a stage and finished after the earliest running one was admitted,
    at its real finish, so a launch that waited behind a sibling is not replayed as if it started on
    admission. A launch that stopped before any stage (preparation, capacity) never held the lane.
    """
    from studio.native_budget_family_forecast import media_attempts
    attempts = media_attempts(record) if attempts is None else attempts
    running = [attempt['admittedElapsed'] for attempt, _ in attempts if attempt['status'] == 'running']
    if not running:
        return []
    rows = [(attempt['admittedElapsed'], None if attempt['status'] == 'running' else attempt['completedElapsed'],
             attempt_forecast(record, clip, attempt) if attempt['status'] == 'running' else 0.0,
             attempt['admittedElapsed'] + attempt['grantedSeconds'])
            for attempt, clip in attempts
            if attempt['status'] == 'running' or (attempt['stages'] and (attempt['completedElapsed'] or 0) > min(running))]
    finished = sorted((row for row in rows if row[1] is not None), key=lambda row: (row[0], row[1]))
    ongoing = sorted((row for row in rows if row[1] is None), key=lambda row: (row[0], row[2], row[3]))
    return finished + ongoing  # finished work is replayed first: it held its slot in the past


def attempt_forecast(record: dict, clip: dict, attempt: dict) -> float:
    """Replay the frozen family demand, including every child's repeated startup/source work."""
    if 'familyForecastSeconds' in attempt:
        return attempt['familyForecastSeconds']
    family = next((row for row in clip.get('sectionFamilies', []) if row['id'] == attempt['id']), None)
    windows = None
    if family and attempt['route'] == 'preview':
        inventory = family['previewInventory']
        frames = sum(end - start for row in inventory for start, end in row['windows'])
        total = family['assignments'][-1]['frameRange'][1]
        windows = (frames * attempt['outputSeconds'] / total, len(inventory))
    elif family:
        windows = (None, len(family['assignments']) + 1)
    return route_seconds(clip_rates(record, clip), attempt['route'], attempt['outputSeconds'], windows)


@lru_cache(maxsize=32)
def heavy_lane_capacity(output_seconds: float | None = None, fmt: str = 'short') -> int:
    """Heavy slots the pool gives renders of this format and output duration: their profile, else 1.

    None (native_batch start, before any duration is known) is the most any Short render
    could get, the ceiling for --pool-slots; every launch forecast passes each known output's own
    duration, and a qualification profile that does not cover it yields exclusive capacity (1).
    Long forecasts remain exclusive without project-bound stages and geometry; Short capacity is never borrowed.
    See native_work_qualification.forecast_mode.
    """
    from native_work_pool_policy import class_capacity, host_identity
    from native_work_qualification import forecast_mode
    return class_capacity(forecast_mode(host_identity(), output_seconds, fmt), 'heavy')


def _known_durations(record: dict, launch: tuple[float | None, str]) -> dict[str, float]:
    """The longest known output duration per format (a Long's declared one included); unknown ones are excluded."""
    rows = [(clip['outputSeconds'] or (clip['output']['outputSeconds'] if output_format(clip) == 'long' else None),
             output_format(clip)) for clip in record['clips'].values()]
    known: dict[str, float] = {}
    for seconds, fmt in rows + [launch]:
        if seconds:
            known[fmt] = max(known.get(fmt, 0.0), seconds)
    return known


def slot_count(record: dict, seconds: float | None = None, fmt: str = 'short') -> int:
    """The forecast never assumes more parallel heavy jobs than every known output's own profile allows:
    each format at its longest known duration (every bound clip's, each Long's declared one and this
    launch's). An output of unknown duration is excluded, not a one-slot throttle."""
    known = _known_durations(record, (seconds, fmt))
    capacities = [heavy_lane_capacity(longest, kind) for kind, longest in sorted(known.items())]
    return max(1, min(record['poolSlots'], min(capacities) if capacities else heavy_lane_capacity()))


def _slot_free(start: float, occupant: tuple, elapsed: float) -> float:
    """When a replayed slot frees: a finished launch at its real finish, a running one at its
    forecast end, and an overrunning one only when its grant ends. occupant = (completed, duration, grant end)."""
    completed, duration, grant_end = occupant
    if completed is not None:
        return max(start, completed)  # a finish never moves a slot's free time back
    end = start + duration
    return end if end > elapsed else max(grant_end, elapsed)


def slot_free_times(record: dict, elapsed: float, seconds: float | None = None, fmt: str = 'short') -> list[float]:
    """Replay FIFO slot assignment from the first admission: when each heavy slot frees (running launches of
    every format hold theirs; none is preempted). ``seconds``/``fmt`` name the launch being forecast."""
    occupants = queue_occupants(record)
    return replay_queue(occupants, elapsed, slot_count(record, seconds, fmt))


def replay_queue(occupants: list, elapsed: float, capacity: int) -> list[float]:
    """Pure FIFO replay; an overrun still holds its original hard grant at the final clock sample."""
    slots = [min((row[0] for row in occupants), default=elapsed)] * capacity
    for admitted, *occupant in occupants:
        index = slots.index(min(slots))
        slots[index] = _slot_free(max(slots[index], admitted), tuple(occupant), elapsed)
    return slots


def queue_start_delay(record: dict, elapsed: float, seconds: float | None = None, fmt: str = 'short') -> float:
    """A new launch's wait from now, from the replayed slots."""
    return max(min(slot_free_times(record, elapsed, seconds, fmt)) - elapsed, 0.0)


def promotable_draft_end(record: dict, clip_id: str, project: str | None, elapsed: float) -> float | None:
    """When the clip's running or delivered draft OF THIS PROJECT is done, or None without one.

    A preview leads to a promotion only of a same-project draft; any other draft (another folder,
    a failed one) leaves a final as the preview's following export.
    """
    drafts = [row for row in record['clips'][clip_id]['attempts'] if row['route'] == 'draft'
              and row['project'] == project and row['status'] in ('running', 'succeeded')]
    if not drafts:
        return None
    if drafts[-1]['status'] == 'succeeded':
        return drafts[-1]['completedElapsed']
    forecast_end = drafts[-1]['admittedElapsed'] + route_seconds(record['rates'], 'draft', drafts[-1]['outputSeconds'])
    return max(forecast_end, elapsed)  # an overrunning draft is still running now


def launch_fits(record: dict, launch: tuple, elapsed: float, snapshot: object | None = None) -> dict:
    """Queue delay + own forecast must end before the handoff reserve (and, for previews, must
    still leave room for the export that follows it). launch = (clip, route, seconds[, project[, windows]]):
    ``windows`` is a Long preview packet's summed window seconds (None: the whole-program bound).
    A promotion follows only a same-project draft and starts once both the preview and the draft end."""
    clip_id, route, seconds, project, windows = (*launch, None, None)[:5]
    if len(launch) > 5 and launch[5] > 1:
        windows = (windows, launch[5])
    clip = record['clips'][clip_id]
    rates, deadlines, fmt = clip_rates(record, clip), clip_deadlines(record, clip), output_format(clip)
    service = service_allowance(clip, route, launch[7] if len(launch) > 7 else 0.0)
    delay = (max(min(snapshot.slots(record, elapsed, True)) - elapsed, 0.0) if snapshot is not None
             else queue_start_delay(record, elapsed, seconds, fmt))
    own = route_seconds(rates, route, seconds, windows) + (service if route == 'final' else 0.0)
    draft_end = promotable_draft_end(record, clip_id, project, elapsed) if route == 'preview' else None
    following = 'promote' if draft_end is not None and fmt == 'short' else 'final'
    following_members = launch[6] if len(launch) > 6 else windows[1] if type(windows) is tuple else 1
    following_work = (None, following_members) if following_members > 1 else None
    follow = route_seconds(rates, following, seconds, following_work) + service if route == 'preview' else 0.0
    finish = max(elapsed + delay + own, draft_end or 0.0) + follow
    limit = deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']
    from studio.production.queue_clock import enabled
    counted_finish = finish - delay if enabled(clip) else finish
    return {'fits': counted_finish <= limit, 'forecastCountedFinishElapsed': counted_finish, 'queueDelaySeconds': round(delay, 1),
            'forecastSeconds': round(own, 1), 'followingExportSeconds': round(follow, 1),
            'forecastFinishElapsed': round(finish, 1), 'latestFinishElapsed': limit,
            'slots': snapshot.candidate_capacity if snapshot is not None else slot_count(record, seconds, fmt)}


def service_allowance(clip: dict, route: str, seconds: float) -> float:
    """Only Long preview/final admission accepts finite nonnegative operational demand."""
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid Long service forecast')
    if seconds and (output_format(clip) != 'long' or route not in ('preview', 'final')):
        raise ValueError('Service forecast is only for Long preview/final work')
    return seconds
