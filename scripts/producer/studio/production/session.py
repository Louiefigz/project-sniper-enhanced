"""One locked read-modify-write of a batch authority for the production API modules."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from studio.native_budget_binding import advance_clock
from studio.native_budget_store import locked_batch
from studio.production.claims import Outcome
from studio.production.tasks import TaskRefused

Operation = Callable[[dict, float], Outcome]


def transact(root: Path, batch_id: str, operation: Operation) -> dict:
    """One locked read, transition and commit; the refusal (if any) is raised after the commit."""
    with locked_batch(root, batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        outcome = operation(record, elapsed)
        if outcome.changed:
            session.commit(record, {**outcome.event, 'elapsed': round(elapsed, 3)})
    if outcome.refusal:
        raise TaskRefused(outcome.refusal)
    return {**outcome.detail, 'elapsed': round(elapsed, 3), 'committed': outcome.changed}


def read_now(root: Path, batch_id: str) -> tuple[dict, float]:
    """A locked, validated read at the current batch clock (nothing is written)."""
    with locked_batch(root, batch_id) as session:
        record = session.read()
        return record, advance_clock(record)
