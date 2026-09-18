"""Explicit finishing request for the shared source-float-v2 program master.

Finishing means dialogue cleanup (``plan.audioEnhance``), per-window dialogue
gain (``plan.audioGain``) and authored transition SFX
(``plan.transitions[].sfx``). On the source-float path these never touch the
retained raw dialogue bus or the base picture: ``program_finish_bus`` applies
them at program-master time, before music and the single whole-program master.

This module only validates and projects plan vocabulary. It runs no media
command and grants no approval. An unsupported or malformed request is one
explicit reason so admission fails before dependent work; nothing is dropped.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from audio.audio_gain import GainWindow, overlap_error, parse_windows
from audio.sfx_library import resolve as resolve_sfx
from producer_config import AUDIO_ENHANCE

FINISHING_POLICY_VERSION = 1
GAIN_END_SLACK_S = 0.05          # the same window bound tolerance as plan_lint_audio
ENGINE_WHOOSH = "engine-whoosh"  # receipt key for the transition engine's ``sfx: true``
_DISPATCH_SENTINEL = "@"         # catalog presets that are not ffmpeg chains
_ENHANCE_KEYS = {"preset", "rationale"}


@dataclass(frozen=True)
class SfxCue:
    """One authored seam sound: output seam time plus its resolved one-shot."""

    out_time: float
    sfx: str | bool
    lead_s: float
    path: str | None      # None for the engine whoosh until it is synthesized


@dataclass(frozen=True)
class FinishRequest:
    """Validated finishing vocabulary bound to one exact program duration."""

    duration_s: float
    enhance_preset: str | None
    enhance_chain: str | None
    gain: tuple[GainWindow, ...]
    sfx: tuple[SfxCue, ...]

    @property
    def empty(self) -> bool:
        """True when the plan requests no finishing at all."""
        return self.enhance_preset is None and not self.gain and not self.sfx


def sfx_key(cue: SfxCue) -> str:
    """Receipt/source key: the pack name, or the engine whoosh."""
    return ENGINE_WHOOSH if cue.sfx is True else str(cue.sfx)


def _enhance_reason(value: object) -> str | None:
    """Only a catalog ffmpeg chain; dispatch presets need runtimes this path lacks."""
    if value is None:
        return None
    if type(value) is not dict or set(value) - _ENHANCE_KEYS or "preset" not in value:
        return "audioEnhance must be an object {\"preset\": <catalog name>}"
    preset = value["preset"]
    chain = AUDIO_ENHANCE.get(preset) if type(preset) is str else None
    if not chain:
        return (f"audioEnhance preset {preset!r} is not in the catalog "
                f"({', '.join(sorted(AUDIO_ENHANCE))})")
    if chain.startswith(_DISPATCH_SENTINEL):
        return (f"audioEnhance preset {preset!r} dispatches to {chain[1:]}, a separate runtime "
                "with downloaded model weights; the source-float program uses installed local filters only")
    return None


def _gain_reason(value: object) -> str | None:
    """Reuse the executor's own window parser so lint, admission and render agree."""
    if value is None:
        return None
    try:
        windows = parse_windows(value)
    except ValueError as error:
        return f"audioGain: {error}"
    overlap = overlap_error(windows)
    return f"audioGain: {overlap}" if overlap else None


def _sfx_reason(rows: object) -> str | None:
    """Every requested SFX must be a boolean or a built pack item; never fuzzy."""
    if rows is None:
        return None
    if type(rows) is not list:
        return "transitions must be a list"
    for index, row in enumerate(rows):
        if type(row) is not dict:
            return f"transitions[{index}] must be an object"
        value = row.get("sfx", False)
        if type(value) is bool:
            continue
        try:
            resolve_sfx(value)
        except ValueError as error:
            return f"transitions[{index}].sfx: {error}"
    return None


def finishing_reason(plan: dict) -> str | None:
    """First invalid or unsupported finishing field; None when every field is usable."""
    return _enhance_reason(plan.get("audioEnhance")) or _gain_reason(plan.get("audioGain")) \
        or _sfx_reason(plan.get("transitions"))


def finishing_free_plan(plan: dict) -> dict:
    """The same plan without finishing intent; base picture and raw bus ignore it."""
    result = copy.deepcopy(plan)
    result.pop("audioEnhance", None)
    result.pop("audioGain", None)
    rows = result.get("transitions")
    if type(rows) is list:
        result["transitions"] = [{key: value for key, value in row.items() if key != "sfx"}
                                 if type(row) is dict else row for row in rows]
    return result


def _sfx_cues(plan: dict, duration_s: float) -> tuple[SfxCue, ...]:
    """Reuse the transition engine's seam validation and hit-lead semantics exactly."""
    rows = plan.get("transitions") or []
    if not rows:
        return ()
    from motion.transitions import WHOOSH_LEAD_S, parse_events
    cues = []
    for event in parse_events(rows, duration_s):
        if event.sfx is False:
            continue
        if event.sfx is True:
            cues.append(SfxCue(event.out_time, True, WHOOSH_LEAD_S, None))
            continue
        path, lead = resolve_sfx(event.sfx)
        cues.append(SfxCue(event.out_time, event.sfx, lead, path))
    return tuple(cues)


def _bounded_gain(plan: dict, duration_s: float) -> tuple[GainWindow, ...]:
    """Windows are edited-time intervals inside the exact program duration."""
    windows = tuple(parse_windows(plan.get("audioGain") or []))
    for index, window in enumerate(windows):
        if window.out_start < 0 or window.out_end > duration_s + GAIN_END_SLACK_S:
            raise RuntimeError(f"source-float-v2 rejects audioGain[{index}]: window "
                               f"[{window.out_start}, {window.out_end}] is outside the "
                               f"{duration_s:.3f}s program")
    return windows


def finishing_request(plan: dict, duration_s: float) -> FinishRequest | None:
    """Bind validated intent to the exact program duration; None when nothing is requested."""
    if type(duration_s) is not float or not duration_s > 0:
        raise RuntimeError("finishing requires the exact positive program duration")
    reason = finishing_reason(plan)
    if reason:
        raise RuntimeError("source-float-v2 rejects " + reason)
    preset, chain = (plan.get("audioEnhance") or {}).get("preset"), None
    try:
        if preset:
            from audio.audio_enhance import build_filter
            chain = build_filter(preset)
    except ValueError as error:
        raise RuntimeError("source-float-v2 rejects audioEnhance: " + str(error)) from error
    try:
        cues = _sfx_cues(plan, duration_s)
    except ValueError as error:
        raise RuntimeError("source-float-v2 rejects transitions: " + str(error)) from error
    request = FinishRequest(duration_s, preset or None, chain, _bounded_gain(plan, duration_s), cues)
    return None if request.empty else request


def finishing_settings(request: FinishRequest) -> dict:
    """Canonical requested settings for receipts, hashing and revision comparison."""
    return {"policyVersion": FINISHING_POLICY_VERSION,
        "audioEnhance": {"preset": request.enhance_preset} if request.enhance_preset else None,
        "audioGain": [{"outStart": window.out_start, "outEnd": window.out_end, "dB": window.db}
                      for window in request.gain],
        "sfx": [{"outTime": cue.out_time, "sfx": cue.sfx, "leadS": cue.lead_s} for cue in request.sfx]}


def requested_settings(plan: dict, duration_s: float) -> dict | None:
    """What the plan requests now, for comparison with a retained master receipt."""
    request = finishing_request(plan, duration_s)
    return None if request is None else finishing_settings(request)
