"""Least-laxity placement of committed demand on heavy slots (split from ``production.mixed_forecast``, M-059).

Pure list scheduling over the slots' free times. A demand row is read duck-typed (``DemandRow``: the fields of
``mixed_forecast.Demand``), so this module never imports ``mixed_forecast``; ``mixed_forecast`` imports it.
An exclusive launch (the pool runs it alone: every Long while no Long profile is qualified, and a Short no
profile covers) starts once every slot is free and holds them all until it ends. Any other launch takes the
slot that frees first. Nothing is preempted.
"""
from __future__ import annotations

from typing import Protocol

EPSILON = 1e-6


class DemandRow(Protocol):
    """What placement reads from one output's committed demand (``mixed_forecast.Demand``)."""

    clip_id: str
    durations: tuple[float, ...]
    ready: float
    latest_finish: float
    exclude_capacity_wait: bool
    exclusive: bool


def by_laxity(demands: list[DemandRow] | tuple[DemandRow, ...]) -> list[DemandRow]:
    """Least laxity first: the output whose latest safe start (latest finish minus remaining forecast) comes first."""
    return sorted(demands, key=lambda row: (row.latest_finish - sum(row.durations), row.clip_id))


def take_slot(free: list[float], ready: float, duration: float, exclusive: bool) -> float:
    """Place one launch no earlier than ``ready`` and return its end; ``free`` is updated in place.

    A shared launch goes on the slot that frees first; an exclusive one waits for every slot and holds them all.
    """
    if exclusive:
        end = max(max(free), ready) + duration
        free[:] = [end] * len(free)
        return end
    index = min(range(len(free)), key=lambda slot: max(free[slot], ready))
    free[index] = max(free[index], ready) + duration
    return free[index]


def place(slots: list[float] | tuple[float, ...], demands: list[DemandRow] | tuple[DemandRow, ...],
          elapsed: float) -> dict[str, float]:
    """Forecast finish of every demand: least laxity first, each launch on the slot that frees first
    (an exclusive launch on every slot once all are free)."""
    free, finishes = list(slots), {}
    for demand in by_laxity(demands):
        end = max(demand.ready, elapsed)
        for duration in demand.durations:
            end = take_slot(free, end, duration, demand.exclusive)
        finishes[demand.clip_id] = end
    return finishes


def newly_missed(forecasts: tuple[dict, dict], latest: dict, names: set[str]) -> list[str]:
    """Outputs among ``names`` that fit in the first forecast (absent: fit) and miss in the second."""
    before, after = forecasts
    return [name for name in sorted(names)
            if after[name] > latest[name] + EPSILON and before.get(name, -1.0) <= latest[name] + EPSILON]


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
