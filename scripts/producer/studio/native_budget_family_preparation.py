"""Gather family admission evidence before checking its unchanged original clock.

Preparation reads immutable proofs under the caller's batch lock, but never reconciles
statuses or debits work. Final reconciliation must follow the clock checkpoint so Short
productive-time accounting sees the status that applied during the preceding interval.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from native_render_processes import ProcessIdentity, identity_matches
from studio.native_budget_forecast_snapshot import ForecastSnapshot, capture_forecast
from studio.native_budget_launch import LaunchRequest, _process_table, own_identity
from studio.native_budget_family_state import require
from studio.production.lineage import project_format


@dataclass(frozen=True)
class LaunchFacts:
    """An ephemeral exact-candidate read set belonging to this locked record only."""

    launch: LaunchRequest
    forecast: ForecastSnapshot
    format: str
    supervisor: dict
    processes: dict

    def require_launch(self, record: dict, launch: LaunchRequest) -> None:
        """A prepared path cannot borrow another candidate's identity or pricing facts."""
        self.forecast.require_record(record)
        require(launch == self.launch, 'Prepared launch facts belong to another candidate')

    def mixed_inputs(self, record: dict, elapsed: float) -> object:
        """Use reconciled live statuses and the final clock for the existing mixed algorithm."""
        from studio.production.mixed_forecast import forecast_inputs
        windows = {self.launch.clip_id: self.launch.preview_work} if self.launch.window_seconds is not None else None
        return forecast_inputs(record, elapsed, windows, self.forecast)


def prepare_invocation(record: dict, settings: dict) -> None:
    """Read repairs, parent/current proof, prices, format and liveness without changing statuses."""
    from studio.native_budget_family_repair import repair_state
    from studio.native_budget_family_reservation import launch_request, select_family
    from studio.native_segments.review_forecast import require_owner_room
    clip = record['clips'][settings['context']['clipId']]
    settings['repair'] = repair_state(record, settings)
    family = select_family(clip, settings)
    require_owner_room(clip, settings)
    prepare_parent(family, settings)
    launch = launch_request(record, settings)
    forecast = capture_forecast(record, launch)
    fmt = project_format(Path(settings['project']))
    supervisor = own_identity()
    table = _process_table()
    require(identity_matches(table, ProcessIdentity(**supervisor)), 'Family supervisor changed during admission')
    settings['launchFacts'] = LaunchFacts(launch, forecast, fmt, supervisor, table)


def prepare_parent(family: dict | None, settings: dict) -> None:
    """Cold validate the exact prior full request before pure integration checks consume its token."""
    if family is None or settings['options']['sectionId'] is not None:
        return
    previous = [row for row in family['invocations'] if row['sectionId'] is None]
    if not previous:
        return
    from studio.native_budget_family_reservation import validate_review_parent
    validate_review_parent(settings, previous[-1], family['id'])
    settings['validatedReviewParent'] = previous[-1]['id']
