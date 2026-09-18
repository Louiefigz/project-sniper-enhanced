"""Reuse exact completed picture for audio revisions, never its encoded audio."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audio.held_render_graph import held_active_generation
from audio.program_finish_contract import finishing_free_plan
from audio.render_audio_bus import SourceAudioBus
from captions.caption_plan_pipeline import has_explicit_caption_track
from cut_preview_io import bound_json, digest, file_hash
from fingerprints import caption_fingerprint, graphics_fingerprint, video_fingerprint


def picture_reuse_supported(plan: dict) -> bool:
    """Decline external visual dependencies not yet bound by this reuse policy.

    Template/asset/font and transcript bytes need their renderer-resolved proof,
    not only a plan fingerprint. The existing fresh compositor remains enabled.
    """
    return "presenterLayouts" not in plan and not plan.get("graphicsTrack") and not has_explicit_caption_track(plan)


def picture_reuse_input_hash(job: Any, bus: SourceAudioBus) -> str:
    """Bind every visual input and runtime, excluding assemble-time music and finishing.

    ``audioEnhance``/``audioGain`` and ``transitions[].sfx`` shape only the program
    master on this path, so an audio-finishing revision keeps the same picture key."""
    return digest({"domain": "ordinary-audio-revision-picture-v2",
        "baseSha256": file_hash(Path(job.base).absolute()),
        "videoFingerprint": video_fingerprint(finishing_free_plan(job.plan)),
        "graphicsFingerprint": graphics_fingerprint(job.plan),
        "captionFingerprint": caption_fingerprint(job.plan),
        "tools": bus.admission.tools, "code": list(bus.admission.code)})


def _graph_authority(root: Path, output: Path, record: dict) -> dict[str, str] | None:
    """Require an independently held prior graph, not resealed mutable sidecars."""
    generation = held_active_generation(root)
    if generation is None:
        return None
    final = next(row for row in generation.graph["nodes"] if row["nodeId"] == "node-final")
    inputs = final["inputDigests"]
    if inputs.get("picture.reuse") != record["pictureReuseInputHash"]:
        return None
    artifact = next(row for row in generation.execution["artifacts"] if row["nodeId"] == "node-final")
    if artifact["path"] != str(output) or final["outputArtifactHash"] != record["finalSha256"] \
            or inputs.get("audio.programReceipt") != record["programMasterReceiptHash"]:
        raise RuntimeError("audio-only picture differs from held prior render graph")
    return dict(generation.files)


def _receipt(job: Any, bus: SourceAudioBus) -> tuple[dict, dict[str, str]] | None:
    """A stale or absent reuse record means render picture, never fabricate it."""
    from audio.assemble_source_audio import PROGRAM_AUDIO_POINTER
    if not picture_reuse_supported(job.plan):
        return None
    root = Path(job.out).absolute().parent
    if not (root / PROGRAM_AUDIO_POINTER).exists() or not Path(job.out).exists():
        return None
    record = bound_json(root / PROGRAM_AUDIO_POINTER)
    if record.get("schemaVersion") != 2 or record.get("audioClockPolicy") != "source-float-v2" \
            or record.get("pictureReuseInputHash") != picture_reuse_input_hash(job, bus):
        return None
    final_hash = file_hash(Path(job.out).absolute())
    sidecar = bound_json(Path(job.out + ".assembled.json").absolute())
    if final_hash != record.get("finalSha256") or sidecar.get("authorityHash") != final_hash:
        raise RuntimeError("audio-only picture reuse final bytes differ from their receipt")
    held = _graph_authority(root, Path(job.out).absolute(), record)
    return (record, held) if held is not None else None


def reuse_final_picture(job: Any, bus: SourceAudioBus, directory: Path) -> tuple[bool, dict[str, str]]:
    """Copy a proved prior composite; its old AAC is discarded by final audio mux."""
    from audio.assemble_source_audio import PROGRAM_AUDIO_POINTER, _OUTPUT_NAMES, _copy_support
    selection = _receipt(job, bus)
    if selection is None:
        return False, {}
    record, held = selection
    support = record.get("pictureSupportSha256")
    if type(support) is not dict:
        return False, {}
    root = Path(job.out).absolute().parent
    for name, expected in support.items():
        if name not in _OUTPUT_NAMES and not re.fullmatch(r"caption-shard-[0-9a-f]{64}\.mov(?:\.json)?", name):
            raise RuntimeError("audio-only picture support path is not owned")
        _copy_support(root / name, directory / name, expected)
        held[str(root / name)] = expected
    _copy_support(Path(job.out).absolute(), directory / "final.mp4", record["finalSha256"])
    held[str(root / PROGRAM_AUDIO_POINTER)] = file_hash(root / PROGRAM_AUDIO_POINTER)
    if bound_json(root / PROGRAM_AUDIO_POINTER) != record:
        raise RuntimeError("audio-only picture reuse receipt changed")
    return True, held
