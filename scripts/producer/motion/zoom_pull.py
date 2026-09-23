#!/usr/bin/env python3
"""zoom_pull — seam-role zoom-pull transitions (continuity mechanism CM-1).

Doctrine: docs/studies/EDITCRAFT_LESSONS.md §2.7. The variant defaults and
allowed bands are Sniper design parameters, deliberately configurable, in
``producer_config.MOTION["transitions"]["zoom_pull"]``. Three variants, all
an EASED digital zoom bridging (or resolving) a cutTrack seam:

* PUNCH-CUT — a-roll punch-IN (~+20%, bell velocity over 0.25-0.42s) that
  COMPLETES 0.6-1.3s BEFORE the picture cut; the cut itself is covered by a
  light-leak/flash (sequential, never simultaneous — the cover rides the
  same event via ``cover``).
* WHIP — an accelerating zoom that SPANS the cut: ease-in ramp (~1s) into a
  blur-masked peak AT the seam (the blur hides the largest upscale), the
  incoming side settling ease-out (~+20% over ~0.6s) back to wide.
* SETTLE — the incoming shot eases OUT from a slight zoom (under 12%) over
  0.3-0.55s starting within ~0.55s of the cut (soft landing).

PUNCH-ENGINE REUSE: the per-frame ``scale=eval=frame`` + recomputed-crop
idiom (and its even-dim guard) comes from ``motion.punch_in`` — the same
closed forms, so a zoom-pull can never drift from the punch grammar. The
scale trajectory ``scale_at`` is the pure-Python mirror of the ffmpeg
expression, exactly like ``punch_in.ramp_scale_at``.

Executed THROUGH ``motion/transitions.py`` (event kind ``"zoom-pull"``) so
zoom-pulls share the seam-cover contract: sorted, spaced, frame-count
preserved, whoosh SFX slot. Lint: LONGFORM-ONLY, seam-role a-roll<->b-roll,
counted against the transitions density budget (``lint_event`` below is the
single validator plan_lint_motion calls — executor and lint cannot drift).

Event shape (inside plan.transitions):
    {"outTime": 120.0, "kind": "zoom-pull", "variant": "whip",
     "seamRole": "aroll->broll", "sfx": true}
Optional per-variant overrides (validated against the design bands):
    punch-cut: scale, attackS, completeBeforeS, cover ("light-leak" |
               "white-flash" | false; default light-leak)
    whip:      peakScale, rampS, settleScale, settleS
    settle:    fromScale, durS, delayS
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motion.punch_in import _scaled_dim_expr  # noqa: E402  (punch-engine reuse)
from producer_config import MOTION  # noqa: E402

CFG = MOTION["transitions"]["zoom_pull"]
VARIANTS = CFG["variants"]
SEAM_ROLES = CFG["seam_roles"]
COVERS = ("light-leak", "white-flash")


def _clamp01(v: float) -> float:
    """Clamp to [0, 1] (the expression mirrors use it everywhere)."""
    return min(1.0, max(0.0, v))


def _band(i: int, ev: dict, key: str, spec: tuple[str, str]) -> float:
    """Resolve one override against its design band (raises outside it).

    ``spec`` = (default_key, band_key) into the variant's config dict.
    """
    cfg = CFG[ev["variant"].replace("-", "_")]
    default_key, band_key = spec
    raw = ev.get(key, cfg[default_key])
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"event[{i}]: {key} must be a number")
    lo, hi = cfg[band_key]
    if not (lo <= float(raw) <= hi):
        raise ValueError(f"event[{i}]: {key} {raw} outside the design "
                         f"band [{lo},{hi}] (zoom_pull.{band_key})")
    return float(raw)


@dataclass(frozen=True)
class ZoomPullSpec:
    """One resolved zoom-pull: seam time, variant, design-band params.

    ``params`` holds the variant's resolved numbers; ``cover`` is the
    punch-cut seam cover kind ("" = none); ``seam_role`` is advisory
    vocabulary ("" = unstated — the lint WARNs).
    """

    out_time: float
    variant: str
    params: dict = field(default_factory=dict)
    cover: str = ""
    seam_role: str = ""

    @property
    def span(self) -> tuple[float, float]:
        """The full time footprint [t0, t1] the zoom occupies."""
        p, t = self.params, self.out_time
        if self.variant == "punch-cut":
            return t - p["complete_before_s"] - p["attack_s"], t
        if self.variant == "whip":
            return t - p["ramp_s"], t + p["settle_s"]
        return t, t + p["delay_s"] + p["dur_s"]


def _parse_punch_cut(i: int, ev: dict) -> ZoomPullSpec:
    """Variant A: eased punch-in completing before the seam + a seam cover."""
    params = {
        "scale": _band(i, ev, "scale", ("scale", "scale_band")),
        "attack_s": _band(i, ev, "attackS", ("attack_s", "attack_band_s")),
        "complete_before_s": _band(i, ev, "completeBeforeS",
                                   ("complete_before_s", "complete_band_s")),
    }
    cover = ev.get("cover", CFG["punch_cut"]["cover_default"])
    if cover in (False, None):
        cover = ""
    elif cover not in COVERS:
        raise ValueError(f"event[{i}]: cover {cover!r} must be one of "
                         f"{COVERS} or false")
    return ZoomPullSpec(float(ev["outTime"]), "punch-cut", params, cover)


def _parse_whip(i: int, ev: dict) -> ZoomPullSpec:
    """Variant B: accelerating zoom spanning the cut, blur-masked peak."""
    params = {
        "peak_scale": _band(i, ev, "peakScale", ("peak_scale", "peak_band")),
        "ramp_s": _band(i, ev, "rampS", ("ramp_s", "ramp_band_s")),
        "settle_scale": _band(i, ev, "settleScale",
                              ("settle_scale", "settle_band")),
        "settle_s": _band(i, ev, "settleS", ("settle_s", "settle_band_s")),
    }
    return ZoomPullSpec(float(ev["outTime"]), "whip", params)


def _parse_settle(i: int, ev: dict) -> ZoomPullSpec:
    """Variant C: incoming shot zooms out to wide shortly after the cut."""
    params = {
        "from_scale": _band(i, ev, "fromScale", ("from_scale", "from_band")),
        "dur_s": _band(i, ev, "durS", ("dur_s", "dur_band_s")),
    }
    delay = ev.get("delayS", CFG["settle"]["delay_s"])
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) \
            or not (0.0 <= float(delay) <= CFG["settle"]["delay_max_s"]):
        raise ValueError(f"event[{i}]: delayS must be a number in "
                         f"[0,{CFG['settle']['delay_max_s']}]")
    params["delay_s"] = float(delay)
    return ZoomPullSpec(float(ev["outTime"]), "settle", params)


_PARSERS = {"punch-cut": _parse_punch_cut, "whip": _parse_whip,
            "settle": _parse_settle}


def parse_event(i: int, ev: dict, duration: float) -> ZoomPullSpec:
    """Validate one raw ``kind:"zoom-pull"`` event into a ``ZoomPullSpec``.

    Raises ValueError on an unknown variant, an override outside its design
    band, a bad seamRole, or a zoom footprint that leaves ``[0, duration]``.
    """
    variant = ev.get("variant")
    if variant not in VARIANTS:
        raise ValueError(f"event[{i}]: zoom-pull variant {variant!r} not in "
                         f"{VARIANTS}")
    role = ev.get("seamRole", "")
    if role and role not in SEAM_ROLES:
        raise ValueError(f"event[{i}]: seamRole {role!r} not in {SEAM_ROLES} "
                         "(zoom-pulls are a-roll<->b-roll seam markers)")
    spec = _PARSERS[variant](i, ev)
    if role:
        spec = ZoomPullSpec(spec.out_time, spec.variant, spec.params,
                            spec.cover, role)
    t0, t1 = spec.span
    if t0 < 0.0 or t1 > duration:
        raise ValueError(f"event[{i}]: zoom-pull footprint [{t0:.2f},{t1:.2f}]"
                         f" leaves the timeline [0,{duration:.2f}]")
    return spec


def scale_at(spec: ZoomPullSpec, t: float) -> float:
    """The linear scale at output time ``t`` — the pure Python mirror of
    :func:`_zoom_expr` for host-side reasoning + tests (punch_in idiom)."""
    p, seam = spec.params, spec.out_time
    if spec.variant == "punch-cut":
        if t >= seam:
            return 1.0
        prog = _clamp01((t - (seam - p["complete_before_s"] - p["attack_s"]))
                        / p["attack_s"])
        return 1.0 + (p["scale"] - 1.0) * prog * prog * (3.0 - 2.0 * prog)
    if spec.variant == "whip":
        if t < seam:
            prog = _clamp01((t - (seam - p["ramp_s"])) / p["ramp_s"])
            return 1.0 + (p["peak_scale"] - 1.0) * prog ** 3
        q = _clamp01((t - seam) / p["settle_s"])
        return 1.0 + (p["settle_scale"] - 1.0) * (1.0 - q) ** 2
    if t < seam:
        return 1.0
    if t < seam + p["delay_s"]:
        return p["from_scale"]
    r = _clamp01((t - (seam + p["delay_s"])) / p["dur_s"])
    return 1.0 + (p["from_scale"] - 1.0) * (1.0 - r) ** 2


def _zoom_expr(spec: ZoomPullSpec) -> str:
    """The per-frame linear-scale expression ``z(t)`` (ffmpeg eval syntax).

    Encodes exactly :func:`scale_at`: smoothstep bell for punch-cut (1.0 past
    the seam — the CUT resolves it), accelerating cubic into an eased settle
    for whip, and a delayed power2-out release for settle.
    """
    p, seam = spec.params, spec.out_time
    if spec.variant == "punch-cut":
        t0 = seam - p["complete_before_s"] - p["attack_s"]
        pr = f"clip((t-{t0:.6f})/{p['attack_s']:.6f},0,1)"
        return (f"if(lt(t,{seam:.6f}),"
                f"1+{p['scale'] - 1.0:.6f}*{pr}*{pr}*(3-2*{pr}),1)")
    if spec.variant == "whip":
        pr = f"clip((t-{seam - p['ramp_s']:.6f})/{p['ramp_s']:.6f},0,1)"
        q = f"clip((t-{seam:.6f})/{p['settle_s']:.6f},0,1)"
        return (f"if(lt(t,{seam:.6f}),1+{p['peak_scale'] - 1.0:.6f}*"
                f"pow({pr},3),1+{p['settle_scale'] - 1.0:.6f}*pow(1-{q},2))")
    t1 = seam + p["delay_s"]
    r = f"clip((t-{t1:.6f})/{p['dur_s']:.6f},0,1)"
    return (f"if(lt(t,{seam:.6f}),1,if(lt(t,{t1:.6f}),{p['from_scale']:.6f},"
            f"1+{p['from_scale'] - 1.0:.6f}*pow(1-{r},2)))")


def chain_filters(spec: ZoomPullSpec, width: int, height: int) -> list[str]:
    """Linear-chain filter strings rendering one zoom-pull (1:1 frame count).

    A per-frame ``scale`` (punch_in's even-dim closed form) + a centred crop
    recomputed from the SAME ``z(t)`` (the punch-engine crop rule: crop's
    ``in_w`` constants freeze at link config, so the scaled dims must be
    re-derived from ``t``). z(t)=1 outside the footprint = a no-op resample.
    The whip adds a fixed-sigma gaussian blur gated to ±``blur_span_s``
    around the seam — the blur-masked peak that hides the splice.
    """
    z = _zoom_expr(spec)
    sw = _scaled_dim_expr(width, z)
    sh = _scaled_dim_expr(height, z)
    parts = [f"scale=w='{sw}':h='{sh}':eval=frame,"
             f"crop={width}:{height}:x='({sw}-{width})/2':"
             f"y='({sh}-{height})/2'"]
    if spec.variant == "whip":
        span = CFG["whip"]["blur_span_s"]
        parts.append(f"gblur=sigma={CFG['whip']['blur_sigma']}:"
                     f"enable='between(t,{spec.out_time - span:.6f},"
                     f"{spec.out_time + span:.6f})'")
    return parts


def lint_event(ev: dict, tag: str, mode: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one plan-level zoom-pull event — the SAME
    validator the primitive runs (``parse_event``), plus the doctrine gates:
    longform-only (Sniper's longform seam grammar, EDITCRAFT_LESSONS §2.7;
    the LL-014 replacement vocabulary) and the a-roll<->b-roll seam-role
    advisory. Density is NOT
    checked here — zoom-pulls count against ``max_per_min`` in
    ``plan_lint_motion.check_transitions`` like every seam cover."""
    errors: list[str] = []
    warnings: list[str] = []
    if mode != "longform":
        errors.append(f"{tag}: zoom-pull is longform seam grammar "
                      "(a-roll<->b-roll seam markers) — illegal in "
                      f"{mode or 'unknown'} mode")
    try:                            # bands/variant: the executor's own parser
        parse_event(0, ev, float("inf"))
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"{tag}: {exc}")
        return errors, warnings
    if not ev.get("seamRole"):
        warnings.append(f"{tag}: zoom-pull without a seamRole — the seam "
                        "grammar puts zoom-pulls at a-roll<->b-roll seams "
                        "only (MOTION['transitions']['seam_roles']); state "
                        "'aroll->broll' or 'broll->aroll'")
    return errors, warnings
