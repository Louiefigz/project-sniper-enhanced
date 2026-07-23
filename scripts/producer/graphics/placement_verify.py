#!/usr/bin/env python3
"""placement_verify — default-on post-composite face clearance (v3 item #5).

``free_space.verify_placement`` re-measures the COMPOSITE render (face +
hair in the final frames) and asserts each graphic's placed bbox clears the
face. It now runs for every anchor-resolved (non-explicit) face-anchored
clip BY DEFAULT — the old ``SNIPER_VERIFY_PLACEMENT`` env gate is gone.

A2's deterministic false-FAIL classes on legal compositions are excused
through the allow-vocabulary as SKIP-with-evidence, never silently:

* pip_hole comps — the footage face lives INSIDE the transparent hole;
* windows overlapping ``brollTrack`` — b-roll replaced the frames (no face);
* windows overlapping hook-card overlays (``titleCards`` occupancy).

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
import sys
from dataclasses import dataclass
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_policy  # noqa: E402
from planner import geometry_calibration  # noqa: E402
from planner.free_space import verify_placement  # noqa: E402
from planner.graphics_anchors import FACE_ANCHORS, _content_bbox  # noqa: E402

VERIFY_GATE = "placement_verify"
gate_policy.register_gate(VERIFY_GATE, "FAIL")

# Environment-degraded placement (no cv2 / probe failure) is ADVISORY but
# never silent (geometry contract v3 #1).
ENV_FALLBACK_GATE = "placement_environment"
gate_policy.register_gate(ENV_FALLBACK_GATE, "WARN")

#: (occlusions key, SKIP evidence) — the brollTrack / hook-card vocabulary.
_OCCLUSION_VOCAB = (
    ("broll", "brollTrack replaces the frames in the window — no face to clear"),
    ("cards", "hook-card overlay occupies the window — card occupancy is "
              "unmodeled"),
)


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


def _skip_reason(clip: dict, occlusions: dict | None) -> str | None:
    """The allow-vocabulary SKIP reason for one clip, or None (verify it)."""
    if clip.get("pipHole"):
        return ("pip_hole comp — the footage face lives inside the "
                "transparent hole; face clearance is inapplicable")
    s, e = float(clip["outStart"]), float(clip["outEnd"])
    for key, why in _OCCLUSION_VOCAB:
        wins = (occlusions or {}).get(key) or []
        if any(s < float(w[1]) and e > float(w[0]) for w in wins):
            return why
    return None


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


def _verify_one(clip: dict, video_out: str, ctx: VerifyContext) -> dict | None:
    """Check one face-anchored clip; return a detail dict only when blocking.

    WARN-severity hits and every SKIP/environment path return ``None`` (log
    + continue — never a raise); a FAIL-severity hit on an anchor-resolved
    placement returns its detail for the caller to fail loudly.
    """
    skip = _skip_reason(clip, ctx.occlusions)
    if skip:
        _declare(ctx, clip, gate_policy.Verdict(VERIFY_GATE, "SKIP", skip,
                                                lane="graphics"),
                 "placement_verify_skip")
        return None
    try:
        placed = _placed_bbox(clip)
        ok, detail = verify_placement(video_out, float(clip["outStart"]),
                                      float(clip["outEnd"]), placed)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        _declare(ctx, clip, gate_policy.Verdict(
            VERIFY_GATE, "SKIP", "verify unavailable — "
            f"{type(exc).__name__}: {str(exc)[:160]}", lane="graphics"),
            "placement_verify_skip")
        return None
    if ok:
        ctx.say(status="placement_verified", anchor=clip.get("anchor"),
                **detail)
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
    if ctx.note:
        ctx.say(status="placement_verify_note",
                **gate_policy.Verdict(VERIFY_GATE, "WARN", ctx.note,
                                      lane="graphics").to_dict())
    checked, failures = 0, []
    for clip in clips:
        if clip.get("anchor") not in FACE_ANCHORS:
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
