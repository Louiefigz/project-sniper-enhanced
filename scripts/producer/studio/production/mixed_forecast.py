"""Mixed admission forecast: does every committed output still finish when one joins or a Long launches?

Model (media only; AI work is not modeled). Heavy slots and when each frees come from the same replay
launch admission uses (``forecast.slot_free_times``): every running launch of any output and format keeps
its slot until its forecast end, or its grant end once it overruns, and is never preempted, so a Long stage
already holding a slot counts in full. Committed demand: every open output (not handed off, not delivered,
before its own deadline) that still needs its minimal deliverable, and "missing" means that deliverable
cannot fit. For a Short it is its review draft, at its known duration (its launched duration, else its
approved script's seconds); a preview's following final is optional demand and never makes a Short that can
still deliver count as missing. For a Long it is its final, preceded by its preview while none ran (today's
Long adapter renders a final only after reviewed previews). A Long preview is forecast from its packet's summed
window seconds when the caller has them, else over the whole program (a bound); ``basis`` says which.
Demand is placed least laxity first (latest finish minus remaining forecast), each launch on the slot that
frees first, a Long's final after its own preview (non-preemptive list scheduling). Long and historical Short waits count on their original clocks. Newly authorized Shorts forecast
occupied-capacity waits separately; real credit still requires verified scheduler observations.

Decisions:
- ``admission_refusal``: an output joins only if it fits its own deadline and no output that fits without
  it misses with it. The refusal names the outputs that miss, what is ahead of them and the running
  launches holding the slots.
- ``long_launch_refusal``: a Long launch starts only if no committed Short that fits now would miss with
  the Long holding a slot from now. An authorized Long is never stopped; only its next launch waits.

Bound on a Long waiting behind urgent Shorts: its launch waits only while it would make a committed Short
that still fits miss. A Short stops holding it back once it launches, delivers, is handed off, or passes its
own latest safe start (its latest finish minus its forecast; after that it misses whatever the Long does).
So a Long launch waits at most until the latest safe start of the committed Shorts it would delay, never
past their deadlines (2,400 s after the most recent Short's authorization); and no Short is admitted whose
placement pushes an open Long past its own latest finish, so within the model the wait never costs the
Long its deadline.

Seam for A5 (whole-batch pending demand, latest-safe starts): the decisions are pure functions of a
``ForecastInputs`` (slot free times, committed ``Demand`` rows, unknown outputs, running launch names).
``forecast_inputs`` builds one from the authority; A5 builds it from its own replay and pending-demand
rows and passes it in (``inputs=``), keeping its per-output deadlines and rates from ``production.formats``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from studio.native_budget_forecast import attempt_forecast, route_seconds, service_allowance, slot_free_times
from studio.production.formats import clip_deadlines, clip_rates, output_format, preview_basis

EPSILON = 1e-6


@dataclass(frozen=True)
class Demand:
    """One output's remaining required launches, the earliest they can start and their latest finish."""

    clip_id: str
    durations: tuple[float, ...]
    ready: float
    latest_finish: float
    exclude_capacity_wait: bool = False


@dataclass(frozen=True)
class ForecastInputs:
    """What a mixed decision reads: when each heavy slot frees, the committed demand, and names for refusals.

    ``unknown`` names outputs whose demand cannot be counted; ``basis`` says, per Long, how its preview was
    forecast. A5 can supply this from its replay and pending-demand rows.
    """

    slots: tuple[float, ...]
    demands: tuple[Demand, ...]
    unknown: tuple[str, ...] = ()
    running: tuple[str, ...] = ()
    basis: dict = field(default_factory=dict)


def latest_finish(record: dict, clip: dict) -> float:
    """The output's own delivery deadline less its hand-off reserve."""
    deadlines = clip_deadlines(record, clip)
    return deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']


def _conservative_end(record: dict, clip: dict, attempt: dict, elapsed: float) -> float:
    """When a running launch frees its slot: its forecast end, or its grant end once it overruns."""
    end = attempt['admittedElapsed'] + attempt_forecast(record, clip, attempt)
    return end if end > elapsed else max(attempt['admittedElapsed'] + attempt['grantedSeconds'], elapsed)


def _short_routes(clip: dict) -> tuple[tuple[str, ...], float | None]:
    """A Short without a visible MP4 or a running full-program launch needs its minimal deliverable: a draft."""
    if clip['deliveries'] or any(row['status'] == 'running' and row['route'] != 'preview' for row in clip['attempts']):
        return (), None
    seconds = clip['outputSeconds']
    if seconds is None and clip['approvals']:
        seconds = sum(end - start for start, end in clip['approvals'][-1]['ranges'])
    return ('draft',), seconds


def _long_routes(record: dict, clip: dict, elapsed: float) -> tuple[tuple[str, ...], float]:
    """A Long's remaining preview and final, and when the first can start (after a running preview)."""
    states = [(row['route'], row['status']) for row in clip['attempts']]
    if clip['deliveries'] or any(route != 'preview' and status in ('running', 'succeeded') for route, status in states):
        return (), elapsed
    previews = [row for row in clip['attempts'] if row['route'] == 'preview' and row['status'] == 'running']
    if previews:
        return ('final',), _conservative_end(record, clip, previews[-1], elapsed)
    return (('final',) if ('preview', 'succeeded') in states else ('preview', 'final')), elapsed


def _clip_demand(record: dict, clip_id: str, context: tuple[float, float | None],
                 snapshot: object | None = None) -> tuple[Demand | None, bool]:
    """(demand or None, whether its duration is unknown) for one open output. context = (elapsed, windows)."""
    (elapsed, windows), clip = context, record['clips'][clip_id]
    if output_format(clip) == 'long':
        from studio.native_budget_family_forecast import pending_seconds
        pending = pending_seconds(record, clip, snapshot.prices if snapshot is not None else None)
        if pending is not None:
            return (Demand(clip_id, pending, elapsed, latest_finish(record, clip)) if pending else None), False
        (routes, ready), seconds = _long_routes(record, clip, elapsed), clip['output']['outputSeconds']
    else:
        (routes, seconds), ready = _short_routes(clip), elapsed
    if not routes or seconds is None:
        return None, bool(routes)
    rates = clip_rates(record, clip)
    durations = tuple(route_seconds(rates, route, seconds, windows if route == 'preview' else None) for route in routes)
    from studio.production.queue_clock import enabled
    return Demand(clip_id, durations, ready, latest_finish(record, clip), enabled(clip)), False


def forecast_inputs(record: dict, elapsed: float, windows: dict | None = None,
                    snapshot: object | None = None) -> ForecastInputs:
    """The authority's inputs: replayed slots, every open output's committed demand and the running launches.

    ``windows`` maps a Long to its preview packet's summed window seconds (absent: the whole-program bound).
    """
    windows, demands, unknown, basis = windows or {}, [], [], {}
    for clip_id, clip in record['clips'].items():
        if clip['state'] == 'handed-off' or elapsed >= clip_deadlines(record, clip)['deliverySeconds']:
            continue
        if output_format(clip) == 'long':
            basis[clip_id] = preview_basis(windows.get(clip_id))
        demand, missing = _clip_demand(record, clip_id, (elapsed, windows.get(clip_id)), snapshot)
        if missing:
            unknown.append(clip_id)
        elif demand is not None:
            demands.append(demand)
    slots = snapshot.slots(record, elapsed) if snapshot is not None else slot_free_times(record, elapsed)
    media = snapshot.media(record) if snapshot is not None else None
    return ForecastInputs(tuple(slots), tuple(demands), tuple(unknown),
                          tuple(running_launches(record, elapsed, media)), basis)


def by_laxity(demands: list[Demand] | tuple[Demand, ...]) -> list[Demand]:
    """Least laxity first: the output whose latest safe start (latest finish minus remaining forecast) comes first."""
    return sorted(demands, key=lambda row: (row.latest_finish - sum(row.durations), row.clip_id))


def place(slots: list[float] | tuple[float, ...], demands: list[Demand] | tuple[Demand, ...],
          elapsed: float) -> dict[str, float]:
    """Forecast finish of every demand: least laxity first, each launch on the slot that frees first."""
    free, finishes = list(slots), {}
    for demand in by_laxity(demands):
        end = max(demand.ready, elapsed)
        for duration in demand.durations:
            index = min(range(len(free)), key=lambda slot: max(free[slot], end))
            end = max(free[index], end) + duration
            free[index] = end
        finishes[demand.clip_id] = end
    return finishes


def newly_missed(forecasts: tuple[dict, dict], latest: dict, names: set[str]) -> list[str]:
    """Outputs among ``names`` that fit in the first forecast (absent: fit) and miss in the second."""
    before, after = forecasts
    return [name for name in sorted(names)
            if after[name] > latest[name] + EPSILON and before.get(name, -1.0) <= latest[name] + EPSILON]


def admission_misses(inputs: ForecastInputs, clip_id: str, elapsed: float) -> tuple[list[str], dict]:
    """(outputs that newly miss when ``clip_id``'s demand joins, the forecast with it); the candidate is judged
    against its own deadline only."""
    latest = {row.clip_id: row.latest_finish for row in inputs.demands}
    if clip_id not in latest:
        return [], {}
    before = place(inputs.slots, [row for row in inputs.demands if row.clip_id != clip_id], elapsed)
    after = place(inputs.slots, inputs.demands, elapsed)
    judged = (counted_finishes(before, inputs.demands, elapsed), counted_finishes(after, inputs.demands, elapsed))
    return newly_missed(judged, latest, set(latest)), after


def launch_misses(inputs: ForecastInputs, held: Demand, shorts: set[str], elapsed: float) -> tuple[list[str], dict]:
    """(committed ``shorts`` that newly miss when ``held``'s first launch takes the earliest slot now, that
    forecast); ``held`` carries the launched duration first and any launch that must follow it."""
    slots, rest = list(inputs.slots), [row for row in inputs.demands if row.clip_id != held.clip_id]
    index = slots.index(min(slots))
    slots[index] = max(slots[index], elapsed) + held.durations[0]
    if held.durations[1:]:
        rest.append(Demand(held.clip_id, held.durations[1:], elapsed + held.durations[0], held.latest_finish))
    latest = {row.clip_id: row.latest_finish for row in inputs.demands}
    after = place(slots, rest, elapsed)
    before = counted_finishes(place(inputs.slots, inputs.demands, elapsed), inputs.demands, elapsed)
    counted = counted_finishes(after, rest, elapsed)
    return newly_missed((before, counted), latest, shorts), after


def running_launches(record: dict, elapsed: float, media: list | None = None) -> list[str]:
    """The running (non-preemptible) launches holding heavy slots, named for a refusal."""
    from studio.native_budget_family_forecast import media_attempts
    names = {id(clip): clip_id for clip_id, clip in record['clips'].items()}
    return [f'{names[id(clip)]} {output_format(clip)} {row["route"]} owner {row["id"][:8]} (holds a slot until about '
            f'{_conservative_end(record, clip, row, elapsed):.0f}s)'
            for row, clip in (media_attempts(record) if media is None else media) if row['status'] == 'running']


def _describe(record: dict, misses: list[str], forecast: tuple[dict, list[Demand]], inputs: ForecastInputs) -> str:
    """The outputs that would miss, what is placed ahead of each (least slack first), and what holds the slots."""
    after, demands = forecast
    order = [row.clip_id for row in by_laxity(demands)]
    latest = {row.clip_id: row.latest_finish for row in demands}
    missed = '; '.join(f'{name} ({output_format(record["clips"][name])}) would finish at {after[name]:.0f}s, after '
                       f'its latest {latest[name]:.0f}s, behind {", ".join(order[:order.index(name)]) or "nothing"}'
                       for name in misses)
    holding = '; '.join(inputs.running) or 'no launch is running; the committed demand alone does not fit'
    return f'{missed}. Heavy slots: {holding}'


def admission_refusal(record: dict, clip_id: str, elapsed: float, inputs: ForecastInputs | None = None) -> str | None:
    """Why the output ``clip_id`` (already in the record) cannot join now, or None."""
    inputs = inputs or forecast_inputs(record, elapsed)
    if inputs.unknown:
        return (f'Output {clip_id} cannot be admitted: {", ".join(inputs.unknown)} has no known duration (no '
                'launched export and no approved script), so the forecast cannot count its demand')
    misses, after = admission_misses(inputs, clip_id, elapsed)
    if not misses:
        return None
    return (f'Output {clip_id} cannot be admitted: the forecast misses. '
            f'{_describe(record, misses, (after, list(inputs.demands)), inputs)}')


def long_launch_refusal(record: dict, launch: object, elapsed: float, inputs: ForecastInputs | None = None) -> str | None:
    """Why this Long launch (a ``LaunchRequest``) must wait: holding a slot now would make a committed Short miss."""
    clip_id, clip = launch.clip_id, record['clips'][launch.clip_id]
    windows = {clip_id: launch.preview_work} if launch.window_seconds is not None else None
    inputs = inputs or forecast_inputs(record, elapsed, windows)
    if inputs.unknown:
        return (f'The Long launch waits: {", ".join(inputs.unknown)} has no known duration, so it cannot be shown '
                'that launching now leaves every committed Short on time')
    shorts = {row.clip_id for row in inputs.demands if output_format(record['clips'][row.clip_id]) == 'short'}
    if not shorts:
        return None
    rates = clip_rates(record, clip)
    service = service_allowance(clip, launch.route, getattr(launch, 'service_seconds', 0.0))
    routes = (launch.route, 'final') if launch.route == 'preview' else (launch.route,)
    following = (None, launch.following_members) if launch.following_members > 1 else None
    durations = tuple(route_seconds(rates, route, launch.output_seconds,
                      launch.family_work if route == launch.route else following)
                      + (service if route == 'final' else 0.0) for route in routes)
    misses, after = launch_misses(inputs, Demand(clip_id, durations, elapsed, latest_finish(record, clip)),
                                  shorts, elapsed)
    if not misses:
        return None
    rest = [row for row in inputs.demands if row.clip_id != clip_id]
    return (f'Long {clip_id} {launch.route} waits: holding a slot now (about {durations[0]:.0f}s, never preempted) '
            f'would make committed Shorts miss. {_describe(record, misses, (after, rest), inputs)}')


def mixed_status(record: dict, elapsed: float, inputs: ForecastInputs | None = None) -> dict:
    """Each committed output's forecast finish and latest finish, the running launches and each Long's basis."""
    inputs = inputs or forecast_inputs(record, elapsed)
    finishes = place(inputs.slots, inputs.demands, elapsed)
    counted = counted_finishes(finishes, inputs.demands, elapsed)
    return {'outputs': {row.clip_id: {'forecastFinishElapsed': round(finishes[row.clip_id], 1),
                                      'latestFinishElapsed': round(row.latest_finish, 1),
                                      'forecastCountedFinishElapsed': round(counted[row.clip_id], 1),
                                      'fits': counted[row.clip_id] <= row.latest_finish + EPSILON}
                        for row in inputs.demands},
            'unknownDuration': list(inputs.unknown), 'runningLaunches': list(inputs.running),
            'previewBasis': inputs.basis}


def counted_finishes(finishes: dict, demands: list | tuple, elapsed: float) -> dict:
    """Forecast counted work for Short policy while retaining actual slot occupancy.

    This prediction earns no credit. Only observed, non-overlapping scheduler waits
    extend live allocations. Long forecasts and historical Short clocks stay wall based.
    """
    result = dict(finishes)
    for row in demands:
        if row.exclude_capacity_wait and row.clip_id in result:
            result[row.clip_id] = max(row.ready, elapsed) + sum(row.durations)
    return result
