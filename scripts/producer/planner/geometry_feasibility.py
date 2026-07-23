#!/usr/bin/env python3
"""geometry_feasibility — plan-time placement feasibility LINT (v3 item #3).

For each of a short's face-anchored, non-recompose ``graphicsTrack`` entries
this gate composes the DELIVERY geometry the renderer will actually face —
proxy-mezzanine face sampling (:mod:`planner.geometry_proxy`, the REAL
cut_speed/face_track path) × reframe crop × max punch scale — then runs the
REAL ``_choose_region`` against the SHARED occupancy predicate
(:mod:`planner.occupancy`: face+hair, body, caption band honoring
``bandYOffsetPx``) with the comp's MEASURED content bbox (the same
content-hash-cached render ``comp_measure`` warms). No legal region =
WARN-WITH-EVIDENCE while UNCALIBRATED (A3: the margin is an empirical
residual — no FAIL until the calibration ledger exists), carrying the
anatomy evidence so the brain swaps forms PRE-review at zero loop cost.
FLIP CONDITION (v3 item #4): once ``planner.geometry_calibration``'s
residual ledger (``<producer_dir>/.sniper-learning/geometry_residuals.jsonl``)
clears its floors — ``margin_from_residuals`` returns a per-axis p95 —
verdicts are declared at ``severity_for(GATE, "FAIL", calibrated=True)``
and the lint flips WARN→FAIL. It writes NO placement into the plan —
render-time ``resolve_offset_v2`` (now fail-closed) stays the placement
authority on ground-truth pixels.

Out-of-depth compositions REFUSE LOUDLY (SKIP-with-evidence): baselineLook
(recrops before reframe), brollTrack or titleCards overlapping the checked
window (they replace/occupy frames the proxy face model can't see).

Side artifact: ``<producer_dir>/geometry_predictions.json`` — the predicted
expanded-face boxes per window, consumed by the A3 calibration loop (#4).

CLI: geometry_feasibility.py <plan.json> <manifest.json> <producer_dir>
       [--cache-dir DIR] [--proxy-scale S] [--workdir DIR]
prints the gate contract ``{ok, errors, warnings, metrics}``; exit 0 iff ok.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_policy  # noqa: E402
from gate_policy import Verdict, to_gate_json  # noqa: E402
from compile_timeline import compile_plan  # noqa: E402
from graphics.comp_measure import effective_entries, environment_issue  # noqa: E402
from graphics.graphics_render import DEFAULT_CACHE_DIR, render_entry  # noqa: E402
from graphics.pip_hole import entry_has_hole  # noqa: E402
from motion.recompose import requires_recompose  # noqa: E402
from planner import geometry_calibration  # noqa: E402
from planner import geometry_proxy as gproxy  # noqa: E402
from planner.graphics_anchors import (FACE_ANCHORS, _choose_region,  # noqa: E402
                                      _content_bbox)
from planner.occupancy import (OccupancyExtras, build_map,  # noqa: E402
                               no_legal_evidence, plan_band_offset)
from producer_config import CANVAS_BY_ASPECT, MODES  # noqa: E402

GATE = "geometry_feasibility"
gate_policy.register_gate(GATE, "FAIL")

PREDICTIONS_FILENAME = "geometry_predictions.json"


def run_severity(producer_dir: str) -> str:
    """The A3-calibrated verdict severity for this producer dir.

    WARN while the residual ledger is below its floors; the registered FAIL
    default once ``geometry_calibration.calibrated_margin`` returns a value
    (the item #4 WARN→FAIL flip). A corrupt ledger RAISES (pre-wall, loud) —
    calibration state must never be silently guessed.
    """
    margin = geometry_calibration.calibrated_margin(producer_dir)
    return gate_policy.severity_for(GATE, default="FAIL",
                                    calibrated=margin is not None)


@dataclass
class LintRun:
    """One lint invocation's shared state (keeps helpers ≤4 params)."""

    plan: dict
    manifest: dict
    cache_dir: str
    canvas: tuple
    verdicts: list = field(default_factory=list)
    mode: str | None = None
    predictions: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    # A3 discipline: WARN until the margin ledger calibrates (run_severity).
    severity: str = "WARN"


def _overlaps(entry: dict, rows: list) -> bool:
    """True when any row's [outStart, outEnd) intersects the entry's window."""
    s, e = float(entry["outStart"]), float(entry["outEnd"])
    return any(s < float(r["outEnd"]) and e > float(r["outStart"])
               for r in rows or [])


def checked_entries(plan: dict) -> list:
    """The (index, entry) pairs this lint owns.

    Face-anchored, non-recompose, non-pip, no explicit placement — the class
    whose render-time placement runs ``resolve_offset_v2`` (now fail-closed).
    Windows come exit-on-cut clamped via the shared ``effective_entries``.
    """
    out: list = []
    for i, entry in enumerate(effective_entries(plan)):
        if entry.get("anchor", "free-band") not in FACE_ANCHORS:
            continue
        if entry.get("placement") is not None or requires_recompose(entry) \
                or entry_has_hole(entry):
            continue
        out.append((i, entry))
    return out


def applicability_skip(plan: dict) -> str | None:
    """Why the whole plan is out of this lint's depth, or None when checkable.

    baselineLook recrops BEFORE reframe (the composed crop math would be
    wrong); manual reframe layouts skip face_track entirely; non-face
    strategies have no face-relative geometry to compose.
    """
    if plan.get("baselineLook"):
        return ("baselineLook recrops before reframe — composed geometry "
                "needs ground-truth pixels (v3 A1)")
    reframe = plan.get("reframe") or {}
    if reframe.get("layout", "fill") == "split" or reframe.get("crop") is not None:
        return "manual reframe geometry (split/crop) — face_track does not run"
    mode = (plan.get("target") or {}).get("mode")
    strategy = reframe.get("strategy",
                           MODES.get(mode, {}).get("reframe_default", "none"))
    if strategy != "face":
        return f"reframe strategy {strategy!r} — no face-relative crop to compose"
    return None


def entry_depth_skip(entry: dict, plan: dict) -> str | None:
    """Per-entry out-of-depth reason (broll replaces frames; cards occupy)."""
    if _overlaps(entry, plan.get("brollTrack") or []):
        return "brollTrack overlaps the window — b-roll replaces the frames"
    if _overlaps(entry, plan.get("titleCards") or []):
        return "titleCards overlap the window — card occupancy is unmodeled"
    return None


def check_window(run: LintRun, tag: str, entry: dict,
                 geom: "gproxy.DeliveryGeom") -> None:
    """Run the REAL region chooser on one composed window; record the result."""
    band = plan_band_offset(run.plan)
    free_map = build_map(geom.face_px, set(), run.canvas,
                         OccupancyExtras(hair_top=geom.hair_top,
                                         band_y_offset_px=band))
    bbox = run.metrics.setdefault("_compBBox", {}).get(tag)
    if bbox is None:
        rendered = render_entry(entry, run.cache_dir)
        bbox = _content_bbox(rendered["path"])
        run.metrics["_compBBox"][tag] = bbox
    anchor = entry.get("anchor", "free-band")
    region, _fallback = _choose_region(free_map, anchor, bbox, None)
    window = (float(entry["outStart"]), float(entry["outEnd"]))
    prediction = {
        "tag": tag, "kind": entry.get("kind"), "anchor": anchor,
        "window": [window[0], window[1]],
        "expandedFace": [round(v, 1) for v in free_map.expanded_face],
        "facePx": [round(v, 1) for v in geom.face_px],
        "faceWidthFrac": round(geom.face_px[2] / run.canvas[0], 4),
        "hairMeasured": geom.hair_top is not None,
        "punchScale": round(geom.punch_scale, 4),
        "cropStrategy": geom.crop_strategy,
        "contentBBox": [int(v) for v in bbox],
        "region": region.name if region is not None else None,
    }
    run.predictions.append(prediction)
    if region is not None:
        return
    evidence = no_legal_evidence(anchor, bbox, free_map, window)
    evidence["punchScale"] = round(geom.punch_scale, 4)
    run.verdicts.append(Verdict(GATE, run.severity, (
        f"{tag}: no legal region for the measured content — "
        + json.dumps(evidence, sort_keys=True)), lane="graphics",
        mode=run.mode))


def check_entry(run: LintRun, item: tuple, proxy: dict, crops: list) -> None:
    """Compose + check one graphicsTrack entry against every overlapping crop."""
    i, entry = item
    tag = f"graphicsTrack[{i}] {entry.get('kind')}"
    skip = entry_depth_skip(entry, run.plan)
    if skip:
        run.verdicts.append(Verdict(GATE, "SKIP", f"{tag}: {skip}",
                                    lane="graphics", mode=run.mode))
        return
    s, e = float(entry["outStart"]), float(entry["outEnd"])
    face_px, hair = gproxy.observe_window(proxy["path"], s, e)
    if face_px is None:
        run.verdicts.append(Verdict(GATE, "SKIP", (
            f"{tag}: no face detected on the proxy in [{s:.2f}, {e:.2f}] — "
            "cannot compose face-relative geometry"),
            lane="graphics", mode=run.mode))
        return
    punch = gproxy.max_punch(run.metrics["_punch"], s, e)
    for crop in gproxy.crops_for_window(crops, s, e):
        geom = gproxy.compose_delivery_geometry((face_px, hair), crop, punch,
                                                run.canvas)
        check_window(run, tag, entry, geom)


def lint_plan(run: LintRun, producer_dir: str, work_dir: str,
              proxy_scale: float | None = None) -> None:
    """Run the full lint into ``run`` (verdicts + metrics + predictions file).

    Args:
        run: The shared lint state (plan/manifest/cache/canvas).
        producer_dir: Where ``geometry_predictions.json`` is written.
        work_dir: Scratch dir for the proxy mezzanine.
        proxy_scale: Optional proxy downscale override.
    """
    started = time.monotonic()
    entries = checked_entries(run.plan)
    run.metrics.update(checked=len(entries), warned=0, skipped=0)
    if not entries:
        return
    skip = applicability_skip(run.plan)
    if skip is None:
        skip = environment_issue()
        skip = f"environment unavailable — {skip}" if skip else None
    try:
        import cv2  # noqa: F401 — face sampling needs it
    except ImportError as exc:
        skip = skip or f"cv2 unavailable for proxy face sampling: {exc}"
    if skip:
        run.metrics["skipped"] = len(entries)
        run.verdicts.append(Verdict(GATE, "SKIP", (
            f"{skip}; {len(entries)} face-anchored window(s) unchecked "
            "(render-time placement stays the fail-closed authority)"),
            lane="graphics", mode=run.mode))
        return
    run.metrics["_punch"] = gproxy.plan_punch_windows(run.plan)
    proxy = gproxy.render_proxy(run.plan, run.manifest, work_dir, proxy_scale)
    run.metrics.update(proxyRenderS=proxy["elapsedS"],
                       proxyScale=proxy["scale"])
    t_faces = time.monotonic()
    crops = gproxy.reframe_crop_windows(proxy["path"], compile_plan(run.plan))
    run.metrics["faceTrackS"] = round(time.monotonic() - t_faces, 2)
    for item in entries:
        check_entry(run, item, proxy, crops)
    run.metrics["warned"] = sum(1 for v in run.verdicts if v.severity != "SKIP")
    run.metrics["skipped"] = sum(1 for v in run.verdicts if v.severity == "SKIP")
    run.metrics.pop("_compBBox", None)
    run.metrics.pop("_punch", None)
    run.metrics["elapsedS"] = round(time.monotonic() - started, 2)
    with open(os.path.join(producer_dir, PREDICTIONS_FILENAME), "w") as f:
        json.dump({"gate": GATE, "proxyScale": run.metrics.get("proxyScale"),
                   "windows": run.predictions}, f, indent=2)


def main() -> int:
    """CLI entry point printing the ``{ok, errors, warnings}`` gate contract."""
    ap = argparse.ArgumentParser(
        description="PRODUCER plan-time geometry feasibility lint")
    ap.add_argument("plan_path")
    ap.add_argument("manifest_path")
    ap.add_argument("producer_dir")
    ap.add_argument("--cache-dir", default=None,
                    help="content-hash render cache (default: shared cache)")
    ap.add_argument("--proxy-scale", type=float, default=None,
                    help="proxy mezzanine downscale (default: config)")
    ap.add_argument("--workdir", default=None,
                    help="reuse (and keep) this work dir instead of a temp one")
    args = ap.parse_args()
    own_workdir = args.workdir is None
    work_dir = args.workdir or tempfile.mkdtemp(prefix="geometry-lint-")
    try:
        with open(args.plan_path) as f:
            plan = json.load(f)
        with open(args.manifest_path) as f:
            manifest = json.load(f)
        canvas = CANVAS_BY_ASPECT["9:16"]
        mode_raw = (plan.get("target") or {}).get("mode")
        run = LintRun(plan, manifest, args.cache_dir or DEFAULT_CACHE_DIR,
                      (canvas["width"], canvas["height"]),
                      mode=mode_raw if mode_raw in MODES else None,
                      severity=run_severity(args.producer_dir))
        os.makedirs(work_dir, exist_ok=True)
        lint_plan(run, args.producer_dir, work_dir, args.proxy_scale)
        verdict = to_gate_json(run.verdicts, plan.get("target"))
        verdict["metrics"] = run.metrics
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["ok"] else 1
    except (OSError, json.JSONDecodeError, KeyError, ValueError,
            RuntimeError) as exc:
        print(json.dumps({"ok": False,
                          "errors": [f"{GATE}: {exc}"],
                          "warnings": []}, indent=2))
        return 1
    finally:
        if own_workdir:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
