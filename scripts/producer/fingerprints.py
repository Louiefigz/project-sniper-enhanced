#!/usr/bin/env python3
"""fingerprints — the base-reuse content hashes shared by render.py + assemble.py.

Three prints decide what a plan edit costs (assemble.py --auto-base dispatch):

* ``base_fingerprint``  — every field that shapes the BASE (all but graphics/
  music). Unchanged = the base is reusable as-is (legacy single print, kept
  for back-compat reads of old base.fingerprint.json files).
* ``video_fingerprint`` — the base fields EXCEPT the audio-bus fields
  (audioEnhance/audioGain). transitions stay VIDEO-side: their flash frames
  are baked into the picture (the whoosh SFX ride along — see
  audio/base_audio.py for the honest audio-only consequences).
* ``audio_fingerprint`` — {audioEnhance, audioGain} only. video match + audio
  mismatch = the AUDIO-ONLY fast path (rebuild the audio bus, keep the video).

``graphics_fingerprint`` hashes the graphicsTrack for the assembled-output
sidecar so an audio-only mux can prove the existing composite isn't stale.
That sidecar also carries ``plan_content_hash`` (the canonical pixel/audio
contract, excluding editorial decision receipts) and ``file_sha256`` (the exact completed ``final.mp4`` bytes), so a
consumer cannot mistake a same-picture, stale-audio delivery for authority.
"""
from __future__ import annotations

import hashlib
import json
import os

from cross_runtime_canonical_json import canonical_json
from fingerprint_io import (
    assembled_sidecar_path,
    file_sha256,
    invalidate_assembled_sidecar,
    read_recorded_fingerprints,
    stage_receipt_current,
    stage_receipt_path,
    write_json_atomic,
    write_stage_receipt,
)
from graphics_base_effects import graphics_base_effect_projection
from producer_config import MASTERING_POLICY_VERSION

# Fields that do NOT shape the base — excluded from the fingerprint. music is
# applied at ASSEMBLE time (post-master, audio-only), so a music edit must
# never flip the base fingerprint / trigger a base rebuild.
_NON_BASE_KEYS = (
    "graphicsTrack", "graphicsDecisions", "planVersion", "music",
    "persistentText", "cutDecisions", "ending", "transitionRationale",
    "treatmentMap", "chapters", "audioAuthorityMode",
)
_EXPLICIT_CAPTION_KEYS = (
    "captionsTrack", "captionCorrectionLedger", "captionStyles",
    "captionChapters", "captions", "dialogueCaptionAuthority",
)
_NON_RENDER_KEYS = (
    "graphicsDecisions", "planVersion", "persistentText", "cutDecisions",
    "cutRepairPicturePlanAuthority", "ending", "transitionRationale",
    "treatmentMap", "audioAuthorityMode",
)
# The audio BUS fields: applied to the base's audio stream only (video copied),
# so they split out of the video fingerprint for the audio-only fast path.
_AUDIO_KEYS = ("audioEnhance", "audioGain")
_ELEMENT_TRACKS = {
    "cutTrack", "graphicsTrack", "punchIns", "transitions", "audioGain",
    "titleCards", "brollTrack", "treatmentMap", "chapters", "sfxTrack",
}
_ELEMENT_METADATA = {
    "id", "generation", "version", "sourceAnchor", "dependencies",
    "confidence", "evidence", "rationale", "reason", "semanticBeatId",
    "trigger",
}


def json_canon(obj: object) -> object:
    """A JSON-serialization-neutral view: integral floats → ints, recursively.

    The editor's save-plan route round-trips the plan through JS
    ``JSON.stringify``, which collapses ``30.0`` → ``30``; Python's json keeps
    the distinction. Without canonicalization the SAME plan hashes differently
    before and after a UI save, and a zero-change save-plan → assemble flips
    the base fingerprint into a spurious ~3 min full base rebuild.
    """
    if isinstance(obj, bool):          # bool is an int subclass — leave it alone
        return obj
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: json_canon(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_canon(v) for v in obj]
    return obj


def _hash(obj: object) -> str:
    blob = json.dumps(json_canon(obj), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _render_plan_view(plan: dict) -> dict:
    """Strip addressing-only metadata that cannot affect delivered media."""
    result = {key: value for key, value in plan.items()
              if key not in _NON_RENDER_KEYS and not key.startswith("_")}
    for key in _ELEMENT_TRACKS:
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        result[key] = [{name: item for name, item in row.items()
                        if name not in _ELEMENT_METADATA}
                       if isinstance(row, dict) else row
                       for row in rows]
    return result


def _base_plan_view(plan: dict, exclude_audio: bool = False) -> dict:
    """Exact base projection, including graphics-to-base cross-lane effects."""
    view = _render_plan_view(plan)
    excluded = set(_NON_BASE_KEYS)
    if exclude_audio:
        excluded.update(_AUDIO_KEYS)
    if isinstance(plan.get("captionsTrack"), dict):
        excluded.update(_EXPLICIT_CAPTION_KEYS)
    projection = {
        key: value for key, value in view.items()
        if key not in excluded and not key.startswith("_")
    }
    effects = graphics_base_effect_projection(plan)
    if any(effects.values()):
        projection["graphicsBaseEffects"] = effects
    return projection


def plan_content_hash(plan: dict) -> str:
    """Canonical full render-content hash shared with the Palmier sync.

    Version counters, private addressing, graphics IDs, and transcript-derived
    decision receipts do not affect delivered pixels/audio. Everything else,
    including music and audio treatment, must move this full SHA-256.
    """
    content = _render_plan_view(plan)
    blob = canonical_json(content)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stage_fingerprint(payload: object, inputs: list[str]) -> str:
    """Hash one stage's authored payload plus every byte-level input."""
    records = [{"path": os.path.abspath(path), "sha256": file_sha256(path)}
               for path in inputs if path and os.path.exists(path)]
    return _hash({"payload": payload, "inputs": records})


def base_fingerprint(plan: dict) -> str:
    """A content hash of every plan field that shapes the BASE (all but graphics).

    A graphics-only edit leaves this unchanged (base reusable); any cut / zoom /
    transition / audio / caption change flips it (base is stale → re-render).
    """
    return _hash(_base_plan_view(plan))


def base_plan_digest(plan: dict) -> str:
    """Full authority digest of the exact graphics-free plan projection.

    The legacy 16-hex fingerprint remains a dispatch hint. Headless reuse uses
    this domain-separated SHA-256 so a base-reuse decision is never authorized
    by a truncated value.
    """
    projection = _base_plan_view(plan)
    raw = json.dumps(json_canon(projection), sort_keys=True,
                     ensure_ascii=True, separators=(",", ":"),
                     allow_nan=False).encode("ascii")
    return hashlib.sha256(b"sniper-base-plan-v1\0" + raw).hexdigest()


def video_fingerprint(plan: dict) -> str:
    """Base fields EXCEPT the audio-bus fields — the video half of the base."""
    return _hash(_base_plan_view(plan, exclude_audio=True))


def audio_fingerprint(plan: dict) -> str:
    """The audio-bus fields only ({audioEnhance, audioGain})."""
    view = _render_plan_view(plan)
    return _hash({k: view.get(k) for k in _AUDIO_KEYS})


def graphics_fingerprint(plan: dict) -> str:
    """The graphicsTrack hash for the assembled-output staleness sidecar.

    The editor-stamped ``id`` is addressing metadata with ZERO effect on the
    rendered pixels — strip it before hashing so stamping ids (the one-time
    back-compat migration) or an AI round-trip that reshuffles them never
    invalidates a still-current composite (same lesson as ``json_canon``).
    """
    track = _render_plan_view(plan).get("graphicsTrack") or []
    return _hash(track)


def caption_fingerprint(plan: dict) -> str | None:
    """Full domain-separated digest of the post-base caption projection."""
    if not isinstance(plan.get("captionsTrack"), dict):
        return None
    view = _render_plan_view(plan)
    payload = {key: view.get(key) for key in _EXPLICIT_CAPTION_KEYS}
    raw = json.dumps(json_canon(payload), sort_keys=True,
                     ensure_ascii=True, separators=(",", ":"),
                     allow_nan=False).encode("ascii")
    return hashlib.sha256(b"sniper-caption-plan-v1\0" + raw).hexdigest()


def _caption_artifacts_current(authority_path: str, authority: dict) -> None:
    files = authority.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("caption authority has no artifact closure")
    directory = os.path.dirname(authority_path)
    for record in files.values():
        if not isinstance(record, dict) or set(record) != {"name", "sha256"}:
            raise ValueError("caption authority file record is malformed")
        name = record["name"]
        path = os.path.join(directory, str(name))
        valid = (
            os.path.basename(str(name)) == name
            and os.path.isfile(path)
            and file_sha256(path) == record["sha256"]
        )
        if not valid:
            raise ValueError("caption authority artifact is missing or stale")


def _caption_authority_hash(plan: dict, final_path: str) -> str:
    from captions.caption_fingerprints import (
        canonical_digest,
        caption_track_hash,
        correction_ledger_hash,
    )
    from captions.caption_plan_pipeline import validate_plan_caption_authority
    try:
        track, ledger = validate_plan_caption_authority(plan) or (None, None)
    except ValueError as exc:
        raise ValueError("first-class caption plan is malformed") from exc
    if track is None or ledger is None:
        raise ValueError("first-class caption authority disappeared")
    authority_path = os.path.join(
        os.path.dirname(os.path.abspath(final_path)),
        "caption_authority.json")
    try:
        with open(authority_path, encoding="utf-8") as handle:
            authority = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("caption authority is unreadable") from exc
    expected = (
        caption_track_hash(track), correction_ledger_hash(ledger))
    actual = (
        authority.get("captionTrackHash"),
        authority.get("correctionLedgerHash"))
    payload = {key: value for key, value in authority.items()
               if key != "authorityHash"}
    digest = authority.get("authorityHash")
    valid_digest = (
        isinstance(digest, str)
        and digest == canonical_digest(
            "sniper-caption-render-authority-v1", payload))
    if actual != expected or not valid_digest:
        raise ValueError("caption authority does not bind the current plan")
    _caption_artifacts_current(authority_path, authority)
    from captions.caption_shard_authority import validate_bound_shards
    shard_error = validate_bound_shards(
        os.path.dirname(authority_path), authority)
    if shard_error:
        raise ValueError(shard_error)
    return digest


def assembled_fingerprint_record(plan: dict, final_path: str) -> dict:
    """Provenance record for one completed assembled/full-render MP4."""
    record = {"videoFingerprint": video_fingerprint(plan),
              "graphicsFingerprint": graphics_fingerprint(plan),
              "planHash": plan_content_hash(plan),
              "authorityHash": file_sha256(final_path)}
    captions = caption_fingerprint(plan)
    if captions is not None:
        record["captionFingerprint"] = captions
        record["captionAuthorityHash"] = _caption_authority_hash(
            plan, final_path)
    return record


def write_assembled_sidecar(final_path: str, plan: dict) -> dict:
    """Atomically checkpoint plan and byte authority for a completed MP4."""
    record = assembled_fingerprint_record(plan, final_path)
    write_json_atomic(assembled_sidecar_path(final_path), record)
    return record


def fingerprint_record(plan: dict, audio_clock_policy: str = "legacy-v1") -> dict:
    """The full record base.fingerprint.json carries (legacy + split prints)."""
    return {"fingerprint": base_fingerprint(plan),
            "videoFingerprint": video_fingerprint(plan),
            "audioFingerprint": audio_fingerprint(plan),
            "masteringPolicyVersion": MASTERING_POLICY_VERSION,
            "audioClockPolicy": audio_clock_policy}


def recorded_fingerprints(fingerprint_path: str) -> dict:
    """Refresh stored prints from ``base_plan.json`` when it is retained."""
    return read_recorded_fingerprints(fingerprint_path, fingerprint_record)
