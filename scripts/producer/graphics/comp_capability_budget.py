"""Safe-boundary catalog workload estimates, not per-video quality promises."""
from __future__ import annotations

import time
import math
from pathlib import Path

COHORT_SECONDS = 1500
MAX_BYTES = 6 * 1024 ** 3


def _duration_inventory(value: object, count: int) -> dict | None:
    """Never let a malformed estimate suppress a required boundary stop."""
    if value is None:
        return None
    if type(value) is not dict or len(value) != count or any(
            type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not 0 < seconds <= 90 for seconds in value.values()):
        raise RuntimeError("capability projection has invalid duration inventory")
    return value


def projection(value: dict, elapsed: float, count: int) -> tuple:
    """Duration-aware estimate after measured long probes; never reset wall time.

    The continuation's declared empirical model is7s/template +3s per output
    second, with30s whole-run variance reserve. If observed cumulative costs
    exceed that model, scale the remaining estimate upward. This is a workload
    forecast, not a hard latency guarantee or permission to omit any content.
    """
    rows = value["probes"]
    durations = _duration_inventory(value.get("plannedProbeSeconds"), count)
    if not durations:
        mean = sum(row["elapsedMs"] for row in rows) / len(rows) / 1000 if rows else 0
        return elapsed + mean * (count - len(rows)), "mean-row-without-duration-inventory"
    done = {row["kind"] for row in rows}
    remaining = [seconds for kind, seconds in durations.items() if kind not in done]
    expected = sum(7 + 3 * durations[row["kind"]] for row in rows)
    actual = sum(row["elapsedMs"] / 1000 for row in rows)
    scale = max(1, actual / expected) if expected else 1
    estimate = scale * sum(7 + 3 * seconds for seconds in remaining)
    return elapsed + estimate + (30 if remaining else 0), "7s-per-kind+3s-per-output-second;observed-upward-scale;30s-reserve"


def boundary(root: Path, value: dict, started: float, count: int) -> None:
    """Stop between probes, never force-kill active render or mandatory cleanup."""
    elapsed = time.monotonic() - started
    projected, model = projection(value, elapsed, count)
    size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    limit = value.get("cohortLimitSeconds", COHORT_SECONDS)
    value["budget"] = {"elapsedSeconds": round(elapsed, 3), "projectedSeconds": round(projected, 3),
        "projectionModel": model, "artifactBytes": size, "softSeconds": limit, "maxArtifactBytes": MAX_BYTES}
    if value.get("stopRequested") or elapsed >= limit or size > MAX_BYTES \
            or (len(value["probes"]) >= 5 and projected > limit):
        raise RuntimeError("capability cohort stopped at safe boundary; inspect retained budget/projection")
