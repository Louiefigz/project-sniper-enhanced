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
import tempfile

# Fields that do NOT shape the base — excluded from the fingerprint. music is
# applied at ASSEMBLE time (post-master, audio-only), so a music edit must
# never flip the base fingerprint / trigger a base rebuild.
_NON_BASE_KEYS = ("graphicsTrack", "graphicsDecisions", "planVersion", "music",
                  "persistentText")
_NON_RENDER_KEYS = ("graphicsDecisions", "planVersion", "persistentText")
# The audio BUS fields: applied to the base's audio stream only (video copied),
# so they split out of the video fingerprint for the audio-only fast path.
_AUDIO_KEYS = ("audioEnhance", "audioGain")
_ELEMENT_TRACKS = {
    "cutTrack", "graphicsTrack", "punchIns", "transitions", "audioGain",
    "titleCards", "brollTrack", "treatmentMap", "chapters", "sfxTrack",
}
_ELEMENT_METADATA = {"id", "generation", "version", "sourceAnchor",
                     "dependencies"}


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
        ignored = _ELEMENT_METADATA | ({"semanticBeatId"}
                                       if key == "graphicsTrack" else set())
        result[key] = [{name: item for name, item in row.items()
                        if name not in ignored} if isinstance(row, dict) else row
                       for row in rows]
    return result


def plan_content_hash(plan: dict) -> str:
    """Canonical full render-content hash shared with the Palmier sync.

    Version counters, private addressing, graphics IDs, and transcript-derived
    decision receipts do not affect delivered pixels/audio. Everything else,
    including music and audio treatment, must move this full SHA-256.
    """
    content = _render_plan_view(plan)
    blob = json.dumps(json_canon(content), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    """Streaming SHA-256 of a completed file without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stage_fingerprint(payload: object, inputs: list[str]) -> str:
    """Hash one stage's authored payload plus every byte-level input."""
    records = [{"path": os.path.abspath(path), "sha256": file_sha256(path)}
               for path in inputs if path and os.path.exists(path)]
    return _hash({"payload": payload, "inputs": records})


def stage_receipt_path(output_path: str) -> str:
    """Sidecar proving which inputs produced a resumable stage output."""
    return output_path + ".stage.json"


def stage_receipt_current(output_path: str, fingerprint: str) -> bool:
    """Whether an existing stage output is backed by the expected receipt."""
    if not os.path.exists(output_path):
        return False
    try:
        with open(stage_receipt_path(output_path), encoding="utf-8") as handle:
            return json.load(handle).get("fingerprint") == fingerprint
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def write_json_atomic(path: str, payload: object,
                      indent: int | None = None) -> None:
    """Durably write ``payload`` as JSON to ``path`` (tmp + fsync + replace).

    The file is never truncated in place: readers see either the old or the
    new complete document, and once this returns the bytes are fsynced — the
    ordering guarantee the audio-only intent/commit protocol relies on.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, staged = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.",
                                  suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def write_stage_receipt(output_path: str, fingerprint: str) -> None:
    """Atomically bind one completed intermediate to its stage fingerprint."""
    write_json_atomic(stage_receipt_path(output_path),
                      {"fingerprint": fingerprint})


def base_fingerprint(plan: dict) -> str:
    """A content hash of every plan field that shapes the BASE (all but graphics).

    A graphics-only edit leaves this unchanged (base reusable); any cut / zoom /
    transition / audio / caption change flips it (base is stale → re-render).
    """
    view = _render_plan_view(plan)
    return _hash({k: v for k, v in view.items()
                  if k not in _NON_BASE_KEYS and not k.startswith("_")})


def base_plan_digest(plan: dict) -> str:
    """Full authority digest of the exact graphics-free plan projection.

    The legacy 16-hex fingerprint remains a dispatch hint. Headless reuse uses
    this domain-separated SHA-256 so a base-reuse decision is never authorized
    by a truncated value.
    """
    view = _render_plan_view(plan)
    projection = {key: value for key, value in view.items()
                  if key not in _NON_BASE_KEYS and not key.startswith("_")}
    raw = json.dumps(json_canon(projection), sort_keys=True,
                     ensure_ascii=True, separators=(",", ":"),
                     allow_nan=False).encode("ascii")
    return hashlib.sha256(b"sniper-base-plan-v1\0" + raw).hexdigest()


def video_fingerprint(plan: dict) -> str:
    """Base fields EXCEPT the audio-bus fields — the video half of the base."""
    view = _render_plan_view(plan)
    return _hash({k: v for k, v in view.items()
                  if k not in _NON_BASE_KEYS and k not in _AUDIO_KEYS
                  and not k.startswith("_")})


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


def assembled_fingerprint_record(plan: dict, final_path: str) -> dict:
    """Provenance record for one completed assembled/full-render MP4."""
    return {"videoFingerprint": video_fingerprint(plan),
            "graphicsFingerprint": graphics_fingerprint(plan),
            "planHash": plan_content_hash(plan),
            "authorityHash": file_sha256(final_path)}


def assembled_sidecar_path(final_path: str) -> str:
    """Return the provenance sidecar path for ``final_path``."""
    return final_path + ".assembled.json"


def invalidate_assembled_sidecar(final_path: str) -> None:
    """Remove prior provenance before any operation mutates the final MP4."""
    try:
        os.remove(assembled_sidecar_path(final_path))
    except FileNotFoundError:
        pass


def write_assembled_sidecar(final_path: str, plan: dict) -> dict:
    """Atomically checkpoint plan and byte authority for a completed MP4."""
    record = assembled_fingerprint_record(plan, final_path)
    write_json_atomic(assembled_sidecar_path(final_path), record)
    return record


def fingerprint_record(plan: dict) -> dict:
    """The full record base.fingerprint.json carries (legacy + split prints)."""
    return {"fingerprint": base_fingerprint(plan),
            "videoFingerprint": video_fingerprint(plan),
            "audioFingerprint": audio_fingerprint(plan)}


def recorded_fingerprints(fingerprint_path: str) -> dict:
    """Read a base.fingerprint.json; recompute prints from the plan snapshot.

    Every writer of base.fingerprint.json stores the ``base_plan.json``
    snapshot beside it (render.py bookkeeping, ensure_base, the audio-only
    record update) — and that snapshot IS the plan the base was rendered
    from. When it exists, all three prints are recomputed from it with the
    CURRENT hash functions, so bases survive hash-function changes (the
    int/float canonicalization) and pre-split legacy files gain their
    video/audio prints. Without a snapshot the stored prints are returned
    as-is; a mismatch reads as stale (one honest rebuild, never a wrong reuse).
    """
    with open(fingerprint_path) as f:
        rec = json.load(f)
    snap = os.path.join(os.path.dirname(fingerprint_path), "base_plan.json")
    if os.path.exists(snap):
        with open(snap) as f:
            rec.update(fingerprint_record(json.load(f)))
    return rec
