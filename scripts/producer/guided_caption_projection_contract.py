"""Read-only relations for an actually held full CaptionTrackV1 projection.

Reuse the existing shard/page proof vocabulary; do not decode, render, invoke
font resolution, or treat a self-hash as worker provenance.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Callable

from captions.caption_authority import expected_caption_hashes
from captions.caption_fingerprints import canonical_digest
from captions.caption_page_contract import _coverage, _proof, _exact, _MANIFEST_KEYS, _ENTRY_KEYS
from captions.caption_page_media import CaptionPageMediaContext, caption_page_command
from captions.caption_pages import caption_page_key, plan_caption_pages
from captions.caption_shard_contract import validate_caption_shard_manifest
from compile_timeline import TimelineMap
from cut_preview_io import digest
from producer_config import MODES

MAX_CUES = 1024
MAX_PAGES = 256


def _equal(left: object, right: object, label: str) -> None:
    """Canonical equality includes all values and rejects nonfinite payloads."""
    if digest(left) != digest(right):
        raise RuntimeError("held caption " + label + " differs")


def _receipt(value: dict, domain: str) -> None:
    """Validate an existing receipt digest without issuing a replacement."""
    payload = {key: item for key, item in value.items() if key != "authorityHash"}
    if value.get("authorityHash") != canonical_digest(domain, payload):
        raise RuntimeError("held caption receipt digest differs")


def validate_projection(data: dict, documents: tuple[dict, dict],
                        clock: tuple[str, int, int, int], compiler: str) -> None:
    """Bind compilation, explicit plan policy, timeline and full output clock."""
    plan, timeline = documents
    compilation, authority, shards, pages = (data[key] for key in ("compilation", "authority", "shards", "pages"))
    rate, frames, width, height = clock
    fraction = Fraction(rate)
    if fraction <= 0 or str(fraction) not in {rate, rate.removesuffix('/1')} \
            or any(type(item) is not int or item <= 0 for item in (frames, width, height)):
        raise RuntimeError("held caption full clock is malformed")
    expected_rate = {"numerator": str(fraction.numerator), "denominator": str(fraction.denominator)}
    if len(compilation["cues"]) > MAX_CUES or len(pages["entries"]) > MAX_PAGES:
        raise RuntimeError("held caption projection exceeds bounded cue/page inventory")
    _equal(compilation["fps"], expected_rate, "frame rate")
    _equal(shards["fps"], expected_rate, "shard frame rate")
    _equal(pages["fps"], expected_rate, "page frame rate")
    destination = compilation["destination"]
    if (destination["width"], destination["height"]) != (width, height) or pages["totalFrames"] != frames:
        raise RuntimeError("held caption destination/full frame extent differs")
    for value in (authority, shards, pages):
        _equal(value["destination"], destination, "destination")
    timeline_hash = canonical_digest("sniper-caption-timeline-map-v1", TimelineMap.from_dict(timeline).to_dict())
    if compilation["timelineMapHash"] != timeline_hash or authority["timelineMapHash"] != timeline_hash:
        raise RuntimeError("held caption timeline differs")
    _authority(plan, compilation, authority, compiler)
    validate_caption_shard_manifest(shards)
    _shard_rows(compilation, authority, shards, frames)
    _receipt(pages, "sniper-caption-alpha-page-manifest-v1")
    _exact(pages, _MANIFEST_KEYS, "held caption page manifest")
    if pages["captionAuthorityHash"] != authority["authorityHash"] \
            or pages["shardManifestHash"] != shards["authorityHash"]:
        raise RuntimeError("held caption page parent authority differs")


def _authority(plan: dict, compilation: dict, authority: dict, compiler: str) -> None:
    """Require current caption compiler and exact authored display policy."""
    _receipt(authority, "sniper-caption-render-authority-v1")
    expected = expected_caption_hashes(plan)
    if expected is None or expected != (authority["captionTrackHash"], authority["correctionLedgerHash"]):
        raise RuntimeError("held caption plan authority differs")
    if authority["compilerHash"] != compiler or compilation["compilerHash"] != compiler:
        raise RuntimeError("held caption compiler is stale")
    if authority["compilationHash"] != canonical_digest("sniper-caption-compilation-v1", compilation):
        raise RuntimeError("held caption compilation differs")
    default = MODES.get(plan.get("target", {}).get("mode"), {}).get("captions_burn", False)
    if type(authority["burnExpected"]) is not bool \
            or authority["burnExpected"] != bool(plan.get("captions", {}).get("burn", default)):
        raise RuntimeError("held caption burn policy differs")
    _equal(authority["coverage"], compilation["coverage"], "coverage")
    _equal(authority["cueFingerprints"], {row["cueId"]: row["captionCueFingerprint"]
        for row in compilation["cues"]}, "cue fingerprints")
    _file_roles(compilation, authority)


def _file_roles(compilation: dict, authority: dict) -> None:
    """Only existing Audit B caption outputs may be staged, never arbitrary names."""
    expected = {"compilation": "caption_compilation.json", "ass": "captions.ass",
        "srt": "captions.srt", "palmier": "caption_palmier.json", "shards": "caption_shards.json"}
    if "chapterProjection" in compilation:
        expected.update({"chaptersJson": "caption_chapters.json", "chaptersText": "chapters.txt"})
    shard_roles = {"shard:" + row["cueId"] for row in compilation["cues"]}
    if set(authority["files"]) != set(expected) | shard_roles:
        raise RuntimeError("held caption artifact role inventory differs")
    for key, name in expected.items():
        if authority["files"][key]["name"] != name:
            raise RuntimeError("held caption artifact role path differs")


def _shard_rows(compilation: dict, authority: dict, shards: dict, frames: int) -> None:
    """Keep all cues, including later-body cues and their exact local origins."""
    cues, rows = compilation["cues"], shards["entries"]
    if [row["cueId"] for row in rows] != [row["cueId"] for row in cues] \
            or authority["alphaShardManifestHash"] != shards["authorityHash"]:
        raise RuntimeError("held caption shard coverage differs")
    keys = ("cueId", "placedShardKey", "contentAssetKey", "startFrame", "endFrameExclusive")
    for cue, row in zip(cues, rows, strict=True):
        _equal({key: row[key] for key in keys}, {key: cue[key] for key in keys}, "cue asset timing")
        if row["endFrameExclusive"] > frames:
            raise RuntimeError("held caption cue exceeds the complete picture")
        _equal(authority["files"]["shard:" + row["cueId"]], row["media"], "authority shard bytes")


def validate_shard_receipt(receipt: dict, entry: dict) -> None:
    """The actual renderer sidecar must equal every held manifest entry field."""
    expected = {"schemaVersion": 1, "kind": "caption-alpha-shard-authority", **entry}
    _equal({key: value for key, value in receipt.items() if key != "authorityHash"}, expected, "shard receipt")
    _receipt(receipt, "sniper-caption-alpha-shard-authority-v1")


def validate_pages(data: dict, root: Path, context: tuple) -> None:
    """Reuse exact page planning/command/proof checks without cache reads/writes."""
    pages, shards = data["pages"], data["shards"]
    read, tools, compositor = context
    if pages["compositorHash"] != compositor:
        raise RuntimeError("held caption page compositor is stale")
    rate = Fraction(int(pages["fps"]["numerator"]), int(pages["fps"]["denominator"]))
    if pages["maxPageFrames"] != max(1, int(rate * 30)):
        raise RuntimeError("held caption page duration policy differs")
    planned = plan_caption_pages(shards, pages["totalFrames"], pages["maxPageFrames"])
    if len(planned) != len(pages["entries"]):
        raise RuntimeError("held caption page coverage differs")
    context = CaptionPageMediaContext(shards, str(root), tools)
    receipts = []
    for page, entry in zip(planned, pages["entries"], strict=True):
        _exact(entry, _ENTRY_KEYS, "held caption page entry")
        receipt = read(entry["media"]["name"] + ".json")
        _page_receipt(receipt, entry, page, (pages, context))
        receipts.append(receipt)
    _coverage(receipts, shards)


def _page_receipt(receipt: dict, entry: dict, page: dict, context: tuple) -> None:
    """Bind exact cue crops, page origins, ordered z layers and returned PNG proof."""
    manifest, media_context = context
    key = caption_page_key(manifest, manifest["compositorHash"], page)
    name = f"caption-page-{key}.mov"
    if entry["pageId"] != key or entry["media"]["name"] != name:
        raise RuntimeError("held caption page media identity differs")
    expected = {"schemaVersion": 1, "kind": "caption-alpha-page-authority",
        "pageId": key, "startFrame": page["startFrame"], "endFrameExclusive": page["endFrameExclusive"],
        "cueIds": [row["cueId"] for row in page["inputs"]], "inputs": page["inputs"],
        "captionAuthorityHash": manifest["captionAuthorityHash"], "shardManifestHash": manifest["shardManifestHash"],
        "compositorHash": manifest["compositorHash"], "media": entry["media"], "proof": entry["proof"],
        "command": caption_page_command(page, media_context, str(Path(media_context.directory) / name))}
    _equal({key: value for key, value in receipt.items() if key != "authorityHash"}, expected, "page receipt")
    _equal(entry, {key: receipt[key] for key in entry}, "page entry")
    _receipt(receipt, "sniper-caption-alpha-page-authority-v1")
    _proof(receipt["proof"], manifest, page["endFrameExclusive"] - page["startFrame"])
