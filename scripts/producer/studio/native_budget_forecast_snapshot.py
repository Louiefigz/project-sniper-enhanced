"""Transaction-local read facts for pure admission after the final original-clock sample.

These objects are never serialized or reused across batch locks. They retain prices,
not slot free times: liveness, deadline and overrun decisions use the final elapsed time.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio.native_budget_family_forecast import family_members, member_duration, media_attempts
from studio.native_budget_forecast import queue_occupants, replay_queue, slot_count
from studio.production.formats import output_format


@dataclass(frozen=True)
class ForecastSnapshot:
    """Read-only prices and tested capacities, bound to one held authority record."""

    record: dict
    prices: dict
    candidate_capacity: int
    mixed_capacity: int

    def slots(self, record: dict, elapsed: float, candidate: bool = False) -> list[float]:
        """Replay actual reconciled occupants at the decision time without rereading proofs."""
        self.require_record(record)
        occupants = queue_occupants(record, self.media(record))
        return replay_queue(occupants, elapsed, self.candidate_capacity if candidate else self.mixed_capacity)

    def media(self, record: dict) -> list[tuple[dict, dict]]:
        """Project current statuses onto the pre-read numeric member costs."""
        self.require_record(record)
        return media_attempts(record, self.prices)

    def require_record(self, record: dict) -> None:
        """Reject accidental reuse under another transaction or copied authority."""
        if record is not self.record:
            raise ValueError('Forecast snapshot belongs to another authority transaction')


def capture_forecast(record: dict, launch: object) -> ForecastSnapshot:
    """Read needed family costs and both capacity queries before the last clock sample."""
    prices = {}
    for clip in record['clips'].values():
        prices.update(clip_prices(record, clip))
    candidate = slot_count(record, launch.output_seconds, output_format(record['clips'][launch.clip_id]))
    return ForecastSnapshot(record, prices, candidate, slot_count(record))


def clip_prices(record: dict, clip: dict) -> dict:
    """Read each needed family's inventory once; completed history has no proof dependency."""
    from studio.native_segments.review_forecast import pending_work
    families = clip.get('sectionFamilies', [])
    if not families:
        return {}
    attempts = {row['id']: row for row in clip['attempts']}
    current = families[-1]['plan']
    delivered = any(row['kind'] == 'final' and row['attemptId'] == family['id']
                    for family in families if family['plan'] == current for row in clip['deliveries'])
    prices = {}
    for family in families:
        attempt = attempts[family['id']]
        needed = family['plan'] == current and not delivered
        if not needed and not any(row['status'] == 'running' for row in family['invocations']):
            continue
        work = pending_work(family)
        prices.update(family_prices(record, clip, (attempt, family), work))
    return prices


def family_prices(record: dict, clip: dict, context: tuple, work: dict | None) -> dict:
    """Include prospective final prices for preview families without claiming completed final work."""
    attempt, family = context
    routes = ('preview', 'final') if attempt['route'] == 'preview' else ('final',)
    return {(attempt['id'], route, member['sectionId']):
            member_duration(record, clip, ({**attempt, 'route': route}, work), member)
            for route in routes for member in family_members(family, route)}
