#!/usr/bin/env python3
"""placement_verify — default-on post-composite face clearance (v3 item #5).

``free_space.verify_placement`` re-measures the COMPOSITE render (face +
hair in the final frames) and asserts each graphic's placed bbox clears the
face. It runs for every anchor-resolved face placement, including a
``free-band`` clip marked face-aware by the shared placement authority.

A2's deterministic false-FAIL classes on legal compositions are excused
through the allow-vocabulary as SKIP-with-evidence, never silently:

* pip_hole comps — the footage face lives INSIDE the transparent hole;
* only the intervals covered by ``brollTrack`` (b-roll replaces those frames);
* only the intervals covered by hook-card overlays (``titleCards`` occupancy).

Partial coverage never exempts the remaining graphic. Every uncovered span
gets its own measurement and evidence, including after an earlier probe fails.

Operator-explicit placements ARE verified, but a hit is WARN-with-evidence,
NEVER FAIL — the pin is the operator's call. Verdict severity honors the A3
calibration flag (:mod:`planner.geometry_calibration` — see its docstring
for the flip condition): WARN until the margin ledger calibrates, then the
registered FAIL default. A verify hit in WARN mode NEVER raises — log +
continue, the wedge-after-wall class stays dead. Environment failures (no
cv2, probe errors) SKIP-with-evidence in every mode: environment is never a
geometry verdict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_policy  # noqa: E402
from planner import geometry_calibration  # noqa: E402
from planner.free_space import verify_placement  # noqa: E402
from planner.graphics_anchors import FACE_ANCHORS, _content_bbox  # noqa: E402
from graphics.placement_coverage import placement_spans  # noqa: E402
from planner.verified_frame_sampling import FrameIndex, selected_frame_samples  # noqa: E402
from producer_config import FREE_SPACE  # noqa: E402

VERIFY_GATE = "placement_verify"
gate_policy.register_gate(VERIFY_GATE, "FAIL")

# Environment-degraded placement (no cv2 / probe failure) is ADVISORY but
# never silent (geometry contract v3 #1).
ENV_FALLBACK_GATE = "placement_environment"
gate_policy.register_gate(ENV_FALLBACK_GATE, "WARN")

@dataclass
class VerifyContext:
    """One verify pass's shared knobs (keeps the helpers ≤4 params).

    Attributes:
        severity: ``"WARN"`` (uncalibrated) or ``"FAIL"`` (calibrated) —
            see :func:`resolve_severity`.
        occlusions: ``{"broll": [[s, e], ...], "cards": [[s, e], ...]}``
            plan windows for the allow-vocabulary (``None`` = none known).
        emit: NDJSON status emitter (``graphics_stage.emit``); ``None`` mutes.
        note: Optional advisory to declare before checking (e.g. an
            unreadable calibration ledger).
    """

    severity: str
    occlusions: Optional[dict] = None
    emit: Optional[Callable] = None
    note: Optional[str] = None
    frame_index: FrameIndex | None = field(default=None, init=False)

    def say(self, **fields) -> None:
        """Forward one status row to the emitter when one is wired."""
        if self.emit is not None:
            self.emit(stage="graphics", **fields)


def occlusion_windows(plan: dict) -> dict:
    """The plan windows the allow-vocabulary excuses (broll + hook cards).

    Args:
        plan: The edit plan.

    Returns:
        ``{"broll": [[s, e], ...], "cards": [[s, e], ...]}``.
    """
    def _wins(rows: list | None) -> list:
        return [[float(r["outStart"]), float(r["outEnd"])] for r in rows or []]

    return {"broll": _wins(plan.get("brollTrack")),
            "cards": _wins(plan.get("titleCards"))}


def stage_cli_args(plan: dict, occl_path: str,
                   producer_dir: str | None) -> list:
    """The graphics-stage CLI args for verify + the A3 calibration loop.

    Writes the plan's broll/hook-card occlusion windows (the verify
    allow-vocabulary) to ``occl_path`` and threads the producer dir (residual
    journaling + the calibrated WARN→FAIL flip) and the plan's caption band
    offset (the shared occupancy predicate must model the band where captions
    actually render).
    """
    from planner.occupancy import plan_band_offset
    with open(occl_path, "w") as f:
        json.dump(occlusion_windows(plan), f)
    args = ["--occlusions", occl_path,
            "--band-y-offset", str(plan_band_offset(plan))]
    if producer_dir:
        args += ["--producer-dir", producer_dir]
    return args


def declare_env_fallback(emit_fn: Callable, entry: dict,
                         exc: Exception) -> None:
    """Declare a v1 environment-fallback placement loudly via gate policy."""
    verdict = gate_policy.Verdict(
        ENV_FALLBACK_GATE, "WARN",
        "v1-fallback: placement measurement unavailable — "
        f"{type(exc).__name__}: {str(exc)[:160]}", lane="graphics")
    emit_fn(stage="graphics", status="placement_fallback",
            region="v1-fallback", kind=entry.get("kind"),
            outStart=float(entry["outStart"]), **verdict.to_dict())


def resolve_severity(producer_dir: str | None) -> tuple[str, str | None]:
    """The verify severity under the A3 calibration flag + an optional note.

    Args:
        producer_dir: Dir owning the residual ledger; ``None`` = no ledger
            context (standalone CLI) → uncalibrated.

    Returns:
        ``(severity, note)``: ``"FAIL"`` once the margin ledger calibrates,
        else ``"WARN"``. ``note`` is non-None when the ledger exists but is
        unreadable — calibration cannot be PROVEN, so the severity stays
        WARN and the note must be declared loudly (never a silent demotion).
    """
    if not producer_dir:
        return gate_policy.severity_for(VERIFY_GATE, "FAIL",
                                        calibrated=False), None
    try:
        margin = geometry_calibration.calibrated_margin(producer_dir)
    except (OSError, ValueError) as exc:
        return (gate_policy.severity_for(VERIFY_GATE, "FAIL", calibrated=False),
                "calibration ledger unreadable — verify stays WARN: "
                f"{str(exc)[:160]}")
    return gate_policy.severity_for(VERIFY_GATE, "FAIL",
                                    calibrated=margin is not None), None


def _placed_bbox(clip: dict) -> tuple:
    """The clip's landed content bbox (recorded, else re-probed + offset)."""
    placed = clip.get("placedBBox")
    if placed is not None:
        return tuple(placed)
    content = _content_bbox(clip["path"])
    dx, dy = int(clip.get("x", 0)), int(clip.get("y", 0))
    return (content[0] + dx, content[1] + dy, content[2] + dx, content[3] + dy)


def _declare(ctx: VerifyContext, clip: dict, verdict: gate_policy.Verdict,
             status: str) -> None:
    """Emit one verdict row bound to its clip's identity fields."""
    ctx.say(status=status, anchor=clip.get("anchor"),
            outStart=float(clip["outStart"]), outEnd=float(clip["outEnd"]),
            **verdict.to_dict())


def _probe_span(clip: dict, video_out: str, ctx: VerifyContext) -> tuple | None:
    """Choose actual uncovered displayed frames before invoking geometry."""
    bounds = (float(clip["outStart"]), float(clip["outEnd"]))
    if not ctx.occlusions or not any(ctx.occlusions.values()):
        return verify_placement(video_out, *bounds, clip["placedBBox"])
    samples = ctx.frame_index.samples(bounds, ctx.occlusions,
                                       FREE_SPACE["samples_per_window"])
    if not samples:
        _declare(ctx, clip, gate_policy.Verdict(
            VERIFY_GATE, "SKIP", "no unoccluded displayed frame in this interval",
            lane="graphics"), "placement_verify_skip")
        return None
    with selected_frame_samples(video_out, samples):
        ok, detail = verify_placement(video_out, *bounds, clip["placedBBox"])
    return ok, {**detail, "sampledPts": list(samples)}


def _verify_span(clip: dict, video_out: str, ctx: VerifyContext) -> dict | None:
    """Check one uncovered span without suppressing subsequent measurements."""
    try:
        result = _probe_span(clip, video_out, ctx)
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        _declare(ctx, clip, gate_policy.Verdict(
            VERIFY_GATE, "SKIP", "verify unavailable — "
            f"{type(exc).__name__}: {str(exc)[:160]}", lane="graphics"),
            "placement_verify_skip")
        return None
    if result is None:
        return None
    ok, detail = result
    if ok:
        ctx.say(status="placement_verified", anchor=clip.get("anchor"),
                **{**detail, "outStart": float(clip["outStart"]),
                   "outEnd": float(clip["outEnd"])})
        return None
    evidence = json.dumps(detail, sort_keys=True)
    if clip.get("placed"):
        _declare(ctx, clip, gate_policy.Verdict(
            VERIFY_GATE, "WARN", "operator-explicit placement intersects the "
            f"measured face+hair — the pin stands: {evidence}",
            lane="graphics"), "placement_verify_hit")
        return None
    _declare(ctx, clip, gate_policy.Verdict(
        VERIFY_GATE, ctx.severity,
        f"graphic intersects the measured face+hair — {evidence}",
        lane="graphics"), "placement_verify_hit")
    return detail if ctx.severity == "FAIL" else None


def _verify_one(clip: dict, video_out: str, ctx: VerifyContext) -> dict | None:
    """Partition coverage, resolve geometry once, and check every visible span."""
    spans = placement_spans(clip, ctx.occlusions, rendered=bool(ctx.occlusions))
    unavailable, placed = None, None
    try:
        if any(span.reason is None for span in spans):
            placed = _placed_bbox(clip)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        unavailable = f"verify unavailable — {type(exc).__name__}: {str(exc)[:160]}"
    failures = []
    for span in spans:
        scoped = {**clip, "outStart": span.start, "outEnd": span.end,
                  "placedBBox": placed}
        reason = span.reason or unavailable
        if reason:
            _declare(ctx, scoped, gate_policy.Verdict(
                VERIFY_GATE, "SKIP", reason, lane="graphics"), "placement_verify_skip")
            continue
        failure = _verify_span(scoped, video_out, ctx)
        if failure is not None:
            failures.append({**failure, "outStart": span.start, "outEnd": span.end})
    return {"intervalFailures": failures} if failures else None


def run_verify(clips: list, video_out: str, ctx: VerifyContext) -> int:
    """Verify every face-anchored clip against the composite (default-on).

    Args:
        clips: The compositor clip records (``graphics_stage._render_all``).
        video_out: The composited render to re-measure.
        ctx: Severity / occlusions / emitter context.

    Returns:
        The number of clips checked (incl. vocabulary SKIPs).

    Raises:
        RuntimeError: Only in calibrated FAIL mode, when an anchor-resolved
            placement intersects the measured face+hair.
    """
    ctx = replace(ctx)
    ctx.frame_index = FrameIndex(video_out)
    if ctx.note:
        ctx.say(status="placement_verify_note",
                **gate_policy.Verdict(VERIFY_GATE, "WARN", ctx.note,
                                      lane="graphics").to_dict())
    checked, failures = 0, []
    for clip in clips:
        if (clip.get("anchor") not in FACE_ANCHORS
                and not clip.get("faceAware")):
            continue
        checked += 1
        failure = _verify_one(clip, video_out, ctx)
        if failure is not None:
            failures.append(failure)
    if failures:
        # Carry the typed geometry token: a post-wall calibrated FAIL must be
        # routable by the worker's one-shot re-plan route (geometry-replan.ts
        # keys on "NoLegalRegion:"), never an un-routable terminal wedge (A2).
        evidence = json.dumps({"gate": VERIFY_GATE, "failures": failures},
                              sort_keys=True, separators=(",", ":"))
        raise RuntimeError(
            f"placement verify failed for {len(failures)} graphic(s) "
            f"(calibrated FAIL) — NoLegalRegion: {evidence[:1500]}")
    return checked
