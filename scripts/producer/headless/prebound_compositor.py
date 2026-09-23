"""Private R0 compositor using only verified, pre-rendered graphic assets."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from graphics.composite_core import CompositeOptions, build_graph, composite
from graphics.composite_smoothness import YDIF_DUP_FAIL, read_inline_ydif
from graphics.visual_source_policy import require_plan_sources

from .composite_media_checks import (
    MediaCommandConfig,
    alpha_occupancy,
    full_decode_xerror,
    preserved_audio_sha256,
    run_media_command,
)
from .media_probe import ProbeResultV1, artifact_sha256, probe_media_artifact
from .prebound_clips import (
    PreboundClipV1,
    parse_prebound_clips,
    prebound_clip_set_digest,
    validate_prebound_clips,
)
from .prebound_compositor_receipt import (
    AssemblyReceiptInputV1,
    CompositorProofV1,
    build_assembly_receipt,
)
from .prebound_compositor_media import (
    alpha_mode,
    assert_media,
    compatible,
    make_cover,
    media_ref,
)
from .prebound_compositor_build import (
    PreboundCompositorContextV1,
    compositor_build_digest,
    validate_compositor_context,
)
from .prebound_compositor_store import CandidateStore
from .quality_pass_contract import (
    ArtifactRefV1, GraphicAssetRefV1, MediaRefV1, validate_approved_parent)
from .quality_pass_outputs import (
    CandidateMediaV1,
    graphic_asset_set_digest,
    validate_candidate,
)
from .quality_pass_types import CompositeRequestV1


class PreboundCompositorError(RuntimeError):
    """Candidate composition inputs or observed output failed closed."""


@dataclass(frozen=True)
class _ImportedV1:
    store: CandidateStore
    plan: ArtifactRefV1
    base_path: str
    parent_clips_path: str
    asset_paths: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedV1:
    imported: _ImportedV1
    clips: tuple[PreboundClipV1, ...]
    clips_ref: ArtifactRefV1
    rows: tuple[dict, ...]
    base_probe: ProbeResultV1


@dataclass(frozen=True)
class _ObservedV1:
    final: MediaRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    proof: CompositorProofV1


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def _import_inputs(
    request: CompositeRequestV1, context: PreboundCompositorContextV1
) -> _ImportedV1:
    parent = request.candidate.parent
    store = CandidateStore.open(context.candidate_root, context.resolve_artifact)
    try:
        plan = store.write(
            "candidate-plan.json", request.candidate.application.plan_json
        )
        base = store.import_artifact(parent.base.artifact, "base.mp4")
        store.import_artifact(parent.base_receipt, "base-receipt.json")
        store.import_artifact(parent.base_plan, "base-plan.json")
        store.import_artifact(parent.timeline_map, "timeline-map.json")
        clips = store.import_artifact(parent.prebound_clips, "parent-clips.json")
        paths = []
        for asset in request.graphic_assets:
            paths.append(
                store.import_artifact(asset.media.artifact, f"{asset.graphic_id}.mov")
            )
            store.import_artifact(asset.receipt, f"{asset.graphic_id}.receipt.json")
        return _ImportedV1(store, plan, base, clips, tuple(paths))
    except BaseException:
        store.close()
        raise


def _candidate_clip_bytes(
    parent: tuple[PreboundClipV1, ...], assets: tuple[GraphicAssetRefV1, ...]
) -> bytes:
    rows = [json.loads(clip.row_json) for clip in parent]
    by_id = {asset.graphic_id: asset for asset in assets}
    for row in rows:
        asset = by_id[row["graphicId"]]
        row["mediaSha256"] = asset.media.artifact.sha256
        row["renderReceiptSha256"] = asset.receipt.sha256
    return _canonical(rows)


def _prepare(
    request: CompositeRequestV1, context: PreboundCompositorContextV1
) -> _PreparedV1:
    validate_approved_parent(request.candidate.parent)
    plan = request.candidate.application.decoded_plan()
    require_plan_sources(plan)
    require_plan_sources(request.candidate.parent.decoded_plan())
    music = plan.get("music")
    if music is not None and (
        type(music) is not dict or music.get("enabled") is not False
    ):
        raise PreboundCompositorError("R0 requires music disabled in the base")
    imported = _import_inputs(request, context)
    with open(imported.parent_clips_path, "rb") as handle:
        raw = handle.read()
    parent_clips = parse_prebound_clips(raw)
    parent = request.candidate.parent
    validate_prebound_clips(parent_clips, parent.decoded_plan(), parent.graphics_assets)
    candidate_raw = _candidate_clip_bytes(parent_clips, request.graphic_assets)
    clips = parse_prebound_clips(candidate_raw)
    validate_prebound_clips(clips, plan, request.graphic_assets)
    clips_ref = imported.store.write("candidate-clips.json", candidate_raw)
    base_probe = probe_media_artifact(
        imported.base_path, context.ffprobe_path, context.timeout_seconds
    )
    assert_media(base_probe, parent.base)
    rows = []
    for clip, asset, path in zip(clips, request.graphic_assets, imported.asset_paths):
        probe = probe_media_artifact(
            path, context.ffprobe_path, context.timeout_seconds
        )
        assert_media(probe, asset.media)
        if (
            alpha_mode(probe.pixel_format) != "straight"
            or probe.audio_codec is not None
        ):
            raise PreboundCompositorError("R0 graphic is not silent alpha media")
        rows.append(
            {
                "path": path,
                "outStart": clip.out_start,
                "outEnd": clip.out_end,
                "anchor": clip.anchor,
                "x": clip.x,
                "y": clip.y,
            }
        )
    return _PreparedV1(imported, clips, clips_ref, tuple(rows), base_probe)


def _filter_graph_digest(rows: tuple[dict, ...]) -> str:
    graph, _label = build_graph(list(rows), True)
    return hashlib.sha256(
        b"sniper-prebound-filter-graph-v1\0" + graph.encode()
    ).hexdigest()


def _observe(
    prepared: _PreparedV1, context: PreboundCompositorContextV1
) -> _ObservedV1:
    config = MediaCommandConfig(
        context.ffmpeg_path, context.candidate_root, context.timeout_seconds
    )
    occupancies = tuple(
        alpha_occupancy(path, config) for path in prepared.imported.asset_paths
    )
    output = os.path.join(context.candidate_root, ".final.pending.mp4")
    ydif = os.path.join(context.candidate_root, ".ydif.pending.txt")

    def runner(command: list[str]) -> None:
        run_media_command(config, tuple(command[1:]))

    options = CompositeOptions(
        True, ydif, context.ffmpeg_path, context.ffprobe_path, runner
    )
    graph_digest = _filter_graph_digest(prepared.rows)
    passes = composite(
        prepared.imported.base_path, list(prepared.rows), output, options
    )
    duplicate_ratio = read_inline_ydif(ydif)
    if duplicate_ratio >= YDIF_DUP_FAIL:
        raise PreboundCompositorError("candidate failed the YDIF smoothness gate")
    final_path = prepared.imported.store.promote(".final.pending.mp4", "final.mp4")
    final_probe = probe_media_artifact(
        final_path, context.ffprobe_path, context.timeout_seconds
    )
    if not compatible(prepared.base_probe, final_probe):
        raise PreboundCompositorError("candidate changed base media geometry")
    full_decode_xerror(final_path, config)
    base_audio = preserved_audio_sha256(prepared.imported.base_path, final_path, config)
    final = media_ref("final.mp4", final_probe)
    cover, cover_proof = make_cover(prepared.imported.store, final, config)
    proof = CompositorProofV1(
        build_digest=context.expected_build_digest,
        ffmpeg_sha256=artifact_sha256(context.ffmpeg_path),
        ffprobe_sha256=artifact_sha256(context.ffprobe_path),
        filter_graph_digest=graph_digest,
        alpha_occupancy=occupancies,
        passes=passes,
        frames_in=prepared.base_probe.frame_count,
        frames_out=final_probe.frame_count,
        ydif_duplicate_ratio=duplicate_ratio,
        ydif_fail_threshold=YDIF_DUP_FAIL,
        base_audio_sha256=base_audio,
        final_audio_sha256=base_audio,
    )
    return _ObservedV1(final, cover, cover_proof, proof)


def _seal(
    request: CompositeRequestV1,
    prepared: _PreparedV1,
    observed: _ObservedV1,
    context: PreboundCompositorContextV1,
) -> CandidateMediaV1:
    parent = request.candidate.parent
    assets_digest = graphic_asset_set_digest(request.graphic_assets)
    receipt_input = AssemblyReceiptInputV1(
        request.request_digest,
        parent.quality_policy_id,
        parent.ref,
        parent.assembly_receipt.sha256,
        prepared.imported.plan,
        request.candidate.application.after_digest,
        parent.base_projection_digest,
        parent.base,
        parent.base_receipt.sha256,
        parent.timeline_map.sha256,
        request.graphic_assets,
        assets_digest,
        prepared.clips_ref,
        prebound_clip_set_digest(prepared.clips),
        observed.proof,
        observed.final,
        observed.cover,
        observed.cover_proof,
    )
    raw = build_assembly_receipt(receipt_input)
    receipt = prepared.imported.store.write("assembly-receipt.json", raw)
    result = CandidateMediaV1(
        request.candidate.application.after_digest,
        parent.base.artifact.sha256,
        assets_digest,
        observed.final,
        receipt,
        observed.cover,
        observed.cover_proof,
        None,
        "omitted-by-policy",
    )
    validate_candidate(result)
    return result


def compose_prebound_candidate(
    request: CompositeRequestV1, context: PreboundCompositorContextV1
) -> CandidateMediaV1:
    """Recompose one private no-writer/no-base-rebuild R0 MP4 candidate."""
    checked = validate_compositor_context(context)
    prepared = _prepare(request, checked)
    try:
        observed = _observe(prepared, checked)
        result = _seal(request, prepared, observed, checked)
        if compositor_build_digest() != checked.expected_build_digest:
            raise PreboundCompositorError("compositor source changed during run")
        return result
    finally:
        prepared.imported.store.close()
