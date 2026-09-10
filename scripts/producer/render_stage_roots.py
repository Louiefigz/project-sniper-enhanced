#!/usr/bin/env python3
"""Compiler-owned stage-input roots for the current RenderGraphV1 bridge."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from graphics.exit_on_cut import apply_exit_on_cut
from graphics_base_effects import graphics_base_effect_projection
from render_effect_registry import registry_hash, validate_render_documents

_ROW_METADATA = {
    "confidence", "dependencies", "evidence", "generation", "id",
    "rationale", "reason", "semanticBeatId", "sourceAnchor", "trigger",
    "version",
}
_FINAL_FIELDS = (
    "target", "cutTrack", "baselineLook", "reframe", "faceBBoxNorm",
    "punchIns", "brollTrack", "titleCards", "graphicsTrack", "transitions",
    "audioEnhance", "audioGain", "captions", "captionsTrack",
    "captionCorrectionLedger", "captionStyles", "captionChapters",
    "dialogueCaptionAuthority", "chapters", "music",
)
_BASE_FIELDS = (
    "target", "cutTrack", "baselineLook", "reframe", "faceBBoxNorm",
    "punchIns", "brollTrack", "titleCards", "transitions",
    "audioEnhance", "audioGain",
)
_CAPTION_FIELDS = (
    "captions", "captionsTrack", "captionCorrectionLedger", "captionStyles",
    "dialogueCaptionAuthority",
)
_TRACK_FIELDS = {
    "cutTrack", "punchIns", "brollTrack", "titleCards", "graphicsTrack",
    "transitions", "audioGain",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _root(name: str, payload: object) -> str:
    envelope = {
        "domain": f"sniper-render-stage-root-v1:{name}",
        "registryHash": registry_hash(),
        "payload": payload,
    }
    return hashlib.sha256(_canonical(envelope)).hexdigest()


def _rows(value: object) -> object:
    if not isinstance(value, list):
        return value
    return [
        {key: item for key, item in row.items() if key not in _ROW_METADATA}
        if isinstance(row, dict) else row
        for row in value
    ]


def _field(plan: dict[str, Any], name: str) -> object:
    value = plan.get(name)
    return _rows(value) if name in _TRACK_FIELDS else value


def effective_scene_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return metadata-free graphics exactly after the cut-driven exit clamp."""
    track, _ = apply_exit_on_cut(plan)
    result = _rows(track)
    return result if isinstance(result, list) else []


def _base_source_plan(plan: dict[str, Any], audio_clock_policy: str) -> dict[str, Any]:
    """The plan the timeline/base stages actually consume under one audio policy.

    Under source-float-v2, audioEnhance/audioGain/transitions[].sfx are applied in
    the retained float program master, never in the base picture or raw bus, so
    they leave the base and timeline roots. Legacy bases bake them in and keep the
    full projection. Composite/final/scene roots are unchanged by this."""
    if audio_clock_policy != "source-float-v2":
        return plan
    from audio.program_finish_contract import finishing_free_plan
    return finishing_free_plan(plan)


def plan_stage_payloads(plan: dict[str, Any], audio_clock_policy: str = "legacy-v1") -> dict[str, object]:
    """Compile exact current plan projections consumed by renderer stages."""
    validate_render_documents(plan)
    explicit = isinstance(plan.get("captionsTrack"), dict)
    source = _base_source_plan(plan, audio_clock_policy)
    base = {key: _field(source, key) for key in _BASE_FIELDS if key in source}
    if not explicit and "captions" in plan:
        base["captions"] = plan["captions"]
    effects = graphics_base_effect_projection(plan)
    if any(effects.values()):
        base["graphicsBaseEffects"] = effects
    scenes = effective_scene_rows(plan)
    composite_fields = (
        "brollTrack", "titleCards", *_CAPTION_FIELDS,
    )
    composite = {
        key: _field(plan, key) for key in composite_fields if key in plan
    }
    composite["graphicsTrack"] = scenes
    final = {key: _field(plan, key) for key in _FINAL_FIELDS if key in plan}
    if "graphicsTrack" in final:
        final["graphicsTrack"] = scenes
    return {
        "plan.timeline": {"cutTrack": _field(source, "cutTrack")},
        "plan.base": base,
        "plan.composite": composite,
        "plan.final": final,
        **{
            f"plan.scene.{index:04d}": row
            for index, row in enumerate(scenes)
        },
    }


def manifest_stage_payloads(manifest: dict[str, Any]) -> dict[str, object]:
    """Compile asset-manifest roots without ingest-path/timestamp metadata."""
    validate_render_documents({}, manifest)
    sources = manifest.get("sources")
    admission = manifest.get("sourceSetAdmission")
    broll = manifest.get("broll")
    music = manifest.get("music")
    return {
        "manifest.source": {
            "sources": sources, "sourceSetAdmission": admission,
        },
        "manifest.base": {
            "sources": sources, "broll": broll,
            "sourceSetAdmission": admission,
        },
        "manifest.final": {
            "sources": sources, "broll": broll, "music": music,
            "sourceSetAdmission": admission,
        },
    }


def stage_input_roots(
    plan: dict[str, Any], manifest: dict[str, Any], audio_clock_policy: str = "legacy-v1",
) -> dict[str, str]:
    """Return all domain-separated plan/manifest stage roots for one audio policy."""
    payloads = {
        **plan_stage_payloads(plan, audio_clock_policy),
        **manifest_stage_payloads(manifest),
    }
    return {name: _root(name, payload) for name, payload in payloads.items()}


def changed_stage_roots(
    before_plan: dict[str, Any],
    after_plan: dict[str, Any],
    before_manifest: dict[str, Any],
    after_manifest: dict[str, Any],
) -> list[str]:
    """Exact root names changed by one before/after document mutation."""
    before = stage_input_roots(before_plan, before_manifest)
    after = stage_input_roots(after_plan, after_manifest)
    return sorted(
        key for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    )
