"""Separate real family invocations in the media queue from not-yet-dispatched demand."""
from __future__ import annotations

from studio.production.formats import clip_rates


def family_for(clip: dict, attempt: dict) -> dict | None:
    """Resolve the existing logical work inventory without creating any authority."""
    return next((row for row in clip.get('sectionFamilies', []) if row['id'] == attempt['id']), None)


def member_seconds(record: dict, clip: dict, attempt: dict, member: dict) -> float:
    """Forecast one actual child's source/startup work and its own exact picture range."""
    from studio.native_segments.review_forecast import pending_work
    work = pending_work(family_for(clip, attempt)) if attempt['route'] == 'final' else None
    return member_duration(record, clip, (attempt, work), member)


def member_duration(record: dict, clip: dict, context: tuple, member: dict) -> float:
    """Pure member arithmetic over a caller-read package inventory."""
    attempt, work = context
    from studio.native_budget_forecast import route_seconds
    family = family_for(clip, attempt)
    total = family['assignments'][-1]['frameRange'][1]
    seconds = attempt['outputSeconds']
    if attempt['route'] == 'preview':
        frames = sum(end - start for start, end in member['windows'])
        return route_seconds(clip_rates(record, clip), 'preview', seconds, frames * seconds / total)
    bounds = member['frameRange']
    from studio.native_segments.review_forecast import package_seconds
    extra = package_seconds(work, clip_rates(record, clip), member['sectionId'])
    return route_seconds(clip_rates(record, clip), 'final', seconds * (bounds[1] - bounds[0]) / total) + extra


def family_members(family: dict, route: str) -> list[dict]:
    """The complete already-frozen media inventory, with one full final integration."""
    if route == 'preview':
        return family['previewInventory']
    return [*family['assignments'], {'sectionId': None,
                                    'frameRange': [0, family['assignments'][-1]['frameRange'][1]]}]


def media_attempts(record: dict, prices: dict | None = None) -> list[tuple[dict, dict]]:
    """Expand only actual invocation records; logical waiting never occupies a real render lane."""
    rows = []
    for clip in record['clips'].values():
        rows.extend(clip_attempts(record, clip, prices))
    return rows


def clip_attempts(record: dict, clip: dict, prices: dict | None = None) -> list[tuple[dict, dict]]:
    """Represent children as queue-only rows while retaining their original absolute grant end."""
    rows = []
    for attempt in clip['attempts']:
        family = family_for(clip, attempt)
        if family is None:
            rows.append((attempt, clip))
            continue
        rows.extend(invocation_attempts(record, clip, (attempt, family), prices))
    return rows


def invocation_attempts(record: dict, clip: dict, context: tuple, prices: dict | None = None) -> list[tuple[dict, dict]]:
    """Preserve completed actual owners for FIFO history without inventing pending processes."""
    attempt, family = context
    members = {row['sectionId']: row for row in family_members(family, attempt['route'])}
    end = attempt['admittedElapsed'] + attempt['grantedSeconds']
    return [({**attempt, 'id': row['id'], 'status': row['status'],
              'admittedElapsed': row['admittedElapsed'], 'completedElapsed': row['completedElapsed'],
              'grantedSeconds': end - row['admittedElapsed'],
              'stages': [None] if row['requestSha256'] else [],
              'familyForecastSeconds': priced_member(record, clip, (attempt, prices), members[row['sectionId']])
                  if row['status'] == 'running' else 0.0}, clip)
            for row in family['invocations']]


def pending_members(record: dict, clip: dict, attempt: dict, family: dict) -> list[tuple[str | None, float]]:
    """Actual running children are already in queue; only still-required work enters pending demand."""
    return selected_members(record, clip, (attempt, family), None)


def priced_member(record: dict, clip: dict, context: tuple, member: dict) -> float:
    """Prepared transactions require an exact cached price; missing facts cannot trigger late IO."""
    attempt, prices = context
    if prices is not None:
        return prices[(attempt['id'], attempt['route'], member['sectionId'])]
    return member_seconds(record, clip, attempt, member)


def selected_members(record: dict, clip: dict, context: tuple, prices: dict | None) -> list[tuple]:
    """Select still-required members after liveness reconciliation using the same price facts."""
    attempt, family = context
    if family['state'] == 'complete':
        return []
    done = {row['sectionId'] for row in family['invocations'] if row['status'] == 'succeeded'
            and row['resultStatus'] not in ('section-review-pending', 'native-long-rendered-awaiting-qc')}
    running = {row['sectionId'] for row in family['invocations'] if row['status'] == 'running'}
    return [(row['sectionId'], priced_member(record, clip, (attempt, prices), row))
            for row in family_members(family, attempt['route']) if row['sectionId'] not in done | running]


def pending_seconds(record: dict, clip: dict, prices: dict | None = None) -> tuple[float, ...] | None:
    """Order private previews/pictures before late joins; future work consumes clock but holds no lane."""
    if not clip.get('sectionFamilies'):
        return None
    attempts = {row['id']: row for row in clip['attempts']}
    current_plan = clip['sectionFamilies'][-1]['plan']
    selected = {attempts[row['id']]['route']: row for row in clip['sectionFamilies']
                if row['plan'] == current_plan}
    final = selected.get('final')
    if final and any(row['attemptId'] == final['id'] and row['kind'] == 'final' for row in clip['deliveries']):
        return ()
    previews, finals = [], []
    for route, family in selected.items():
        target = previews if route == 'preview' else finals
        target.extend(selected_members(record, clip, (attempts[family['id']], family), prices))
    if 'final' not in selected:
        parent = selected['preview']
        prospective = {**attempts[parent['id']], 'route': 'final'}
        finals = [(row['sectionId'], priced_member(record, clip, (prospective, prices), row))
                  for row in family_members(parent, 'final')]
    return tuple(seconds for key, seconds in previews if key is not None) \
        + tuple(seconds for key, seconds in finals if key is not None) \
        + tuple(seconds for key, seconds in previews if key is None) \
        + tuple(seconds for key, seconds in finals if key is None)
