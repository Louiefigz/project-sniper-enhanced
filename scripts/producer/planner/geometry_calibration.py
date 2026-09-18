#!/usr/bin/env python3
"""geometry_calibration — the A3 empirical margin ledger (v3 item #4).

The Plan-Time Geometry Contract's A3 amendment: any lint clearance margin
must be an EMPIRICAL residual, never a chosen constant. After a successful
graphics composite, the render-time MEASURED expanded-face boxes (the
placement authority's own ``resolve_offset_v2`` measurement, carried on the
``graphics_placements.json`` rows) are compared against the plan-time
PREDICTED boxes (``<producer_dir>/geometry_predictions.json``, written by
:mod:`planner.geometry_feasibility`), and one residual row per axis is
appended to the per-project ledger
``<producer_dir>/.sniper-learning/geometry_residuals.jsonl``::

    {"window": [s, e], "axis": "x0", "predicted": px, "actual": px,
     "residual_px": actual - predicted, "ts": iso-utc, "run": run-id}

(``run`` extends the contract's row shape so "across >= N runs" is
countable; one journal call = one run.)

THE FLIP CONDITION (the WARN→FAIL severity flip this ledger controls):
``geometry_feasibility`` and ``placement_verify`` declare their verdicts at
``gate_policy.severity_for(gate, "FAIL", calibrated=False)`` → WARN until
:func:`margin_from_residuals` returns a value — which requires at least
``GEOMETRY_CALIBRATION["min_windows"]`` distinct ``(run, window)`` samples
across ``GEOMETRY_CALIBRATION["min_runs"]`` distinct runs with every axis
represented. From then on the same call with ``calibrated=True`` restores
the registered FAIL default, and the returned per-axis
``GEOMETRY_CALIBRATION["quantile"]`` of |residual| IS the sanctioned
clearance margin. A ledger below the floors returns ``None``: uncalibrated.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_policy  # noqa: E402
from producer_config import GEOMETRY_CALIBRATION  # noqa: E402

#: Journaling is a learning side-channel on an already-succeeded composite —
#: its own failures are declared WARN (loud), never a wedge.
CALIBRATION_GATE = "geometry_calibration"
gate_policy.register_gate(CALIBRATION_GATE, "WARN")

PREDICTIONS_FILENAME = "geometry_predictions.json"
LEDGER_SUBPATH = os.path.join(".sniper-learning", "geometry_residuals.jsonl")
AXES = ("x0", "y0", "x1", "y1")
_ROW_KEYS = ("window", "axis", "predicted", "actual", "residual_px", "ts",
             "run")
_WINDOW_TOL_S = 1e-3


def ledger_path(producer_dir: str) -> str:
    """The residual ledger path under a producer dir's learning root.

    Args:
        producer_dir: The project's ``producer/`` directory.

    Returns:
        ``<producer_dir>/.sniper-learning/geometry_residuals.jsonl``.
    """
    return os.path.join(producer_dir, LEDGER_SUBPATH)


def _windows_match(pred_window: list, actual: dict) -> bool:
    """True when a prediction's [s, e] equals an actual row's window."""
    starts = abs(float(pred_window[0]) - float(actual["outStart"]))
    ends = abs(float(pred_window[1]) - float(actual["outEnd"]))
    return starts <= _WINDOW_TOL_S and ends <= _WINDOW_TOL_S


def residual_rows(predictions: list, actuals: list, run_id: str,
                  ts: str | None = None) -> list:
    """Match predicted vs measured expanded-face boxes → per-axis rows.

    Actual rows are ``graphics_placements.json`` rows carrying a measured
    ``expandedFace`` (the anchor-resolved v2 class only). A window with
    several predictions (multi-crop reframe) journals one row-set per
    matching prediction against the one measured box — each is an honest
    prediction-error sample of the same window.

    Args:
        predictions: The ``windows`` list of ``geometry_predictions.json``.
        actuals: Placement rows with ``outStart``/``outEnd``/``anchor``/
            ``expandedFace``.
        run_id: Identifier grouping this run's rows (min-runs counting).
        ts: ISO-UTC timestamp; defaults to now.

    Returns:
        The residual rows (may be empty when nothing matches).
    """
    stamp = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list = []
    for actual in actuals:
        measured = actual.get("expandedFace")
        if not measured:
            continue
        for pred in predictions:
            if pred.get("anchor") != actual.get("anchor") \
                    or not _windows_match(pred["window"], actual):
                continue
            window = [float(actual["outStart"]), float(actual["outEnd"])]
            for i, axis in enumerate(AXES):
                predicted, got = float(pred["expandedFace"][i]), float(measured[i])
                rows.append({"window": window, "axis": axis,
                             "predicted": predicted, "actual": got,
                             "residual_px": round(got - predicted, 1),
                             "ts": stamp, "run": run_id})
    return rows


def append_residuals(producer_dir: str, actuals: list,
                     run_id: str | None = None) -> int:
    """Journal one run's residuals against the producer dir's predictions.

    No ``geometry_predictions.json`` (the lint never ran here — e.g. an
    isolated QC-candidate dir) → appends nothing, returns 0.

    Args:
        producer_dir: Dir holding ``geometry_predictions.json`` + the ledger.
        actuals: Placement rows with measured ``expandedFace`` boxes.
        run_id: Optional run identifier (default: timestamp + pid).

    Returns:
        The number of rows appended.

    Raises:
        OSError: On an unreadable predictions file / unwritable ledger.
        ValueError: On a malformed predictions file (incl. JSON errors).
        KeyError: On prediction rows missing contract fields.
    """
    pred_path = os.path.join(producer_dir, PREDICTIONS_FILENAME)
    if not os.path.exists(pred_path):
        return 0
    with open(pred_path) as f:
        predictions = json.load(f).get("windows") or []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run = run_id or f"{stamp}-{os.getpid()}"
    rows = residual_rows(predictions, actuals, run, ts=stamp)
    if not rows:
        return 0
    path = ledger_path(producer_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def journal_actuals(producer_dir: str, rows: list, emit) -> None:
    """Append predicted-vs-measured residuals to the ledger, never blocking.

    ``rows`` are placement sidecar rows; only those carrying a measured
    ``expandedFace`` (the anchor-resolved v2 class) are journaled, against
    ``geometry_predictions.json`` when the feasibility lint wrote one. The
    composite already succeeded — a journaling failure is declared through
    the gate-policy WARN vocabulary via ``emit`` and NEVER raises.
    """
    actuals = [r for r in rows if r.get("expandedFace")]
    if not actuals:
        return
    try:
        appended = append_residuals(producer_dir, actuals)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        verdict = gate_policy.Verdict(
            CALIBRATION_GATE, "WARN",
            f"residual journaling failed — {type(exc).__name__}: "
            f"{str(exc)[:160]}", lane="graphics")
        emit(stage="graphics", status="geometry_residuals_failed",
             **verdict.to_dict())
        return
    if appended:
        emit(stage="graphics", status="geometry_residuals", appended=appended,
             ledger=ledger_path(producer_dir))


def read_ledger(producer_dir: str) -> list:
    """Load every residual row; a missing ledger is an empty (uncalibrated) one.

    Args:
        producer_dir: The project's ``producer/`` directory.

    Returns:
        The parsed rows, oldest first.

    Raises:
        ValueError: On a malformed line or a row missing contract fields —
            LOUD, so a corrupt ledger can never silently change severity.
    """
    path = ledger_path(producer_dir)
    if not os.path.exists(path):
        return []
    rows: list = []
    with open(path) as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: malformed ledger line — {exc}")
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{n}: ledger row must be an object")
            missing = [k for k in _ROW_KEYS if k not in row]
            if missing:
                raise ValueError(f"{path}:{n}: ledger row missing {missing}")
            rows.append(row)
    return rows


def _quantile(values: list, q: float) -> float:
    """Nearest-rank quantile of a non-empty value list."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return float(ordered[rank - 1])


def margin_from_residuals(rows: list, cfg: dict | None = None) -> dict | None:
    """Per-axis |residual| quantile margin, or ``None`` while uncalibrated.

    Args:
        rows: Ledger rows (see :func:`read_ledger`).
        cfg: Override of ``GEOMETRY_CALIBRATION`` (tests).

    Returns:
        ``{"x0": px, "y0": px, "x1": px, "y1": px}`` once the floors are
        cleared (min_windows distinct (run, window) samples across min_runs
        runs, every axis represented); ``None`` below them — the A3
        "WARN until calibrated" state.
    """
    cfg = cfg or GEOMETRY_CALIBRATION
    if not rows:
        return None
    windows = {(row["run"], tuple(row["window"])) for row in rows}
    runs = {row["run"] for row in rows}
    if len(windows) < cfg["min_windows"] or len(runs) < cfg["min_runs"]:
        return None
    by_axis = {axis: [abs(float(r["residual_px"])) for r in rows
                      if r["axis"] == axis] for axis in AXES}
    if not all(by_axis.values()):
        return None
    return {axis: round(_quantile(vals, cfg["quantile"]), 1)
            for axis, vals in by_axis.items()}


def calibrated_margin(producer_dir: str, cfg: dict | None = None) -> dict | None:
    """The producer dir's calibrated margin, or ``None`` while uncalibrated.

    Args:
        producer_dir: The project's ``producer/`` directory.
        cfg: Override of ``GEOMETRY_CALIBRATION`` (tests).

    Returns:
        See :func:`margin_from_residuals`.

    Raises:
        ValueError: On a corrupt ledger (propagated from :func:`read_ledger`).
        OSError: On an unreadable ledger file.
    """
    return margin_from_residuals(read_ledger(producer_dir), cfg)
