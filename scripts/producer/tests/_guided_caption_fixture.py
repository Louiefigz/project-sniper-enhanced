"""TEST-only projection metadata with non-media bytes; never render provenance.

The compiler/JSON/files are real. Decoded proof records below are explicitly
synthetic contract fixtures, not evidence of an executed caption renderer.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from captions.caption_authority import write_caption_artifacts
from captions.caption_fingerprints import canonical_digest
from captions.caption_operations import upsert_caption_range
from captions.caption_page_media import CaptionPageMediaContext, caption_page_command
from captions.caption_pages import CaptionPageSet, caption_page_compositor_identity, caption_page_key, plan_caption_pages
from captions.caption_plan_pipeline import PlanCaptionContext, compile_plan_caption_track
from captions.caption_render import RenderCaptionProjection
from captions.caption_shards import CaptionShardSet
from captions.caption_words import CaptionFrameRate, stable_word_id
from compile_timeline import compile_plan
from guided_caption_dependencies import CaptionFile, hold_caption_file
from guided_caption_projection import CaptionProjectionBinding
from _caption_legacy_fixture import plan as legacy_plan, transcript as legacy_transcript


def guard() -> None:
    """No clock mocked into production; this tiny TEST owner stays synchronous."""


def write(path: Path, value: dict) -> CaptionFile:
    """Write TEST metadata, then hold its actual bytes."""
    path.write_text(json.dumps(value))
    return hold_caption_file(path, guard)


def sealed(domain: str, value: dict) -> dict:
    """Format existing receipt schema; does not authenticate media execution."""
    return {**value, "authorityHash": canonical_digest(domain, value)}


def _font(root: Path) -> dict:
    """Use explicitly fake external font/tool bytes for metadata-only tests."""
    path = root / "TEST-not-a-font.ttf"
    path.write_bytes(b"TEST-only no font or rendered text")
    row = hold_caption_file(path, guard)
    ref = {"path": row.path, "sha256": row.sha256}
    return sealed("sniper-caption-font-closure-v1", {
        "schemaVersion": 1, "kind": "caption-font-closure",
        "tools": {"fcMatch": ref, "fcQuery": ref}, "requests": [],
        "files": [{**ref, "families": ["TEST-only"]}]})


def _stream(compilation: dict, frames: int) -> dict:
    """A deliberately fake decoded-proof shape, never an actual observation."""
    rate, destination = compilation["fps"], compilation["destination"]
    return {"codec_name": "png", "pix_fmt": "rgba", "width": destination["width"],
        "height": destination["height"], "r_frame_rate": f"{rate['numerator']}/{rate['denominator']}",
        "nb_read_frames": str(frames)}


def _shards(compilation: dict, root: Path, font: dict) -> CaptionShardSet:
    """Build closed TEST shard/receipt records with actual non-media file hashes."""
    rows = []
    for cue in compilation["cues"]:
        key = canonical_digest("TEST-not-rendered", cue)
        media = root / f"caption-shard-{key}.mov"
        media.write_bytes(b"TEST NOT A MOV: " + key.encode())
        ref = hold_caption_file(media, guard)
        frames = cue["endFrameExclusive"] - cue["startFrame"]
        safe = compilation["destination"]["safeZones"]
        proof = {"stream": _stream(compilation, frames), "edgeAlphaMax": [255.0, 255.0],
            "shapedSafeBounds": {"minX": safe["left"], "maxX": safe["left"] + 10,
                "minY": safe["top"], "maxY": safe["top"] + 10, "framesMeasured": frames}}
        row = {name: cue[name] for name in ("cueId", "placedShardKey", "contentAssetKey", "startFrame", "endFrameExclusive")}
        row.update({"mediaKey": key, "fps": compilation["fps"], "destination": compilation["destination"],
            "media": {"name": media.name, "sha256": ref.sha256}, "rendererHash": "a" * 64,
            "fontClosureHash": font["authorityHash"], "proof": proof})
        write(Path(str(media) + ".json"), sealed("sniper-caption-alpha-shard-authority-v1",
            {"schemaVersion": 1, "kind": "caption-alpha-shard-authority", **row}))
        rows.append(row)
    return CaptionShardSet(sealed("sniper-caption-alpha-shard-manifest-v1", {
        "schemaVersion": 1, "kind": "caption-alpha-shard-manifest", "fps": compilation["fps"],
        "destination": compilation["destination"], "fontClosure": font, "entries": rows,
        "rendererHash": canonical_digest("sniper-caption-alpha-renderer-set-v1", [row["rendererHash"] for row in rows])}), 0, 0)


def _pages(compilation: dict, shards: dict, authority: dict, root: Path) -> CaptionPageSet:
    """Build the real deterministic page command but never execute it."""
    tools, compositor = caption_page_compositor_identity()
    entries, context = [], CaptionPageMediaContext(shards, str(root), tools)
    for page in plan_caption_pages(shards, 960, 900):
        key = caption_page_key(shards, compositor, page)
        media = root / f"caption-page-{key}.mov"
        media.write_bytes(b"TEST NOT A PAGE: " + key.encode())
        ref = hold_caption_file(media, guard)
        frames = page["endFrameExclusive"] - page["startFrame"]
        proof = {"stream": _stream(compilation, frames), "decodedFrameMd5Sha256": "b" * 64,
                 "alphaMax": 255, "framesMeasured": frames}
        receipt = sealed("sniper-caption-alpha-page-authority-v1", {
            "schemaVersion": 1, "kind": "caption-alpha-page-authority", "pageId": key,
            "startFrame": page["startFrame"], "endFrameExclusive": page["endFrameExclusive"],
            "cueIds": [row["cueId"] for row in page["inputs"]], "inputs": page["inputs"],
            "captionAuthorityHash": authority["authorityHash"], "shardManifestHash": shards["authorityHash"],
            "compositorHash": compositor, "command": caption_page_command(page, context, str(media)),
            "proof": proof, "media": {"name": media.name, "sha256": ref.sha256}})
        write(Path(str(media) + ".json"), receipt)
        entries.append({name: receipt[name] for name in ("pageId", "startFrame", "endFrameExclusive",
            "cueIds", "media", "proof", "authorityHash")})
    manifest = sealed("sniper-caption-alpha-page-manifest-v1", {"schemaVersion": 1,
        "kind": "caption-alpha-page-manifest", "totalFrames": 960, "maxPageFrames": 900,
        "fps": compilation["fps"], "destination": compilation["destination"],
        "captionAuthorityHash": authority["authorityHash"], "shardManifestHash": shards["authorityHash"],
        "compositorHash": compositor, "entries": entries})
    write(root / "caption_pages.json", manifest)
    return CaptionPageSet(manifest, 0, 0)


def fixture(root: Path) -> tuple[SimpleNamespace, CaptionProjectionBinding]:
    """Return TEST typed context plus real held metadata; no source/media authority."""
    source, output = root / "source", root / "original"
    source.mkdir()
    output.mkdir()
    plan, transcript = legacy_plan(), legacy_transcript()
    plan["cutTrack"][0]["end"] = 32
    transcript["transcript"][0]["words"].append({"word": "LATER", "start": 31.1, "end": 31.5})
    plan["captionsTrack"] = upsert_caption_range(plan["captionsTrack"], {
        "wordIds": [stable_word_id("raw-a", 3)], "styleId": "karaoke", "mode": "karaoke-word",
        "placement": "bottom-center"})
    words = write(source / "transcript.json", transcript)
    manifest = {"sources": [{"id": "raw-a", "transcriptPath": "transcript.json"}]}
    plan_ref, manifest_ref = write(root / "edit_plan.json", plan), write(source / "asset_manifest.json", manifest)
    timeline = compile_plan(plan)
    timeline_ref = write(output / "timeline_map.json", timeline.to_dict())
    compilation = compile_plan_caption_track(PlanCaptionContext(plan, manifest, timeline,
        CaptionFrameRate(30, 1), str(source), total_frames=960))
    shards = _shards(compilation, output, _font(root))
    artifacts = write_caption_artifacts(plan, compilation, str(output), shards.manifest)
    pages = _pages(compilation, shards.manifest, artifacts.receipt, output)
    projection = RenderCaptionProjection(compilation, artifacts, shards, pages)
    context = SimpleNamespace(plan=plan, manifest={**manifest, "_path": manifest_ref.path},
        plan_path=plan_ref.path, out_dir=str(output), caption_projection=projection)
    binding = CaptionProjectionBinding(plan_ref, manifest_ref, timeline_ref, ("30", 960, 1080, 1920),
        (words,), "c" * 64)
    return context, binding
