"""Hold actual returned caption projections without generating or approving work.

An in-memory type and these hashes do NOT authenticate a renderer invocation.
The later opening/body owner must supply its actual returned context, separately
held source/pipeline bindings, original deadline and successful cleanup. This
module never selects an on-disk generation, decodes media, or rewrites a cache.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from captions.caption_render import RenderCaptionProjection
from captions.caption_shard_contract import validate_caption_shard_manifest
from cut_preview_io import digest, real_directory
from guided_caption_dependencies import (CaptionFile, Guard, MAX_FILE_BYTES, MAX_FILES, MAX_JSON_BYTES,
    MAX_TOTAL_BYTES, hold_caption_file,
    read_caption_json, stage_caption_files, verify_caption_files)
from guided_caption_projection_contract import (validate_pages, validate_projection,
                                                validate_shard_receipt)
from guided_caption_identity import capture_external, external_paths, projection_identities

_DOCUMENTS = {"compilation": "caption_compilation.json", "authority": "caption_authority.json",
              "shards": "caption_shards.json", "pages": "caption_pages.json"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CaptionProjectionBinding:
    """Owner-held inputs; dependency completeness/source authority remain the owner’s."""

    plan: CaptionFile
    manifest: CaptionFile
    timeline: CaptionFile
    frame_clock: tuple[str, int, int, int]
    dependencies: tuple[CaptionFile, ...]
    execution_input_hash: str


@dataclass(frozen=True)
class HeldCaptionProjection:
    """Exact actual-return caption data with all byte dependencies, not approval."""

    root: str
    binding: CaptionProjectionBinding
    data: dict
    data_hash: str
    files: tuple[CaptionFile, ...]
    external: tuple[CaptionFile, ...]


def _unique(rows: tuple[CaptionFile, ...]) -> tuple[CaptionFile, ...]:
    """Deduplicate equal references only; conflicting independently held facts fail."""
    result = {}
    for row in rows:
        if row.path in result and result[row.path] != row:
            raise RuntimeError("held caption dependency has conflicting identities")
        result[row.path] = row
    return tuple(result[key] for key in sorted(result))


def _binding(binding: CaptionProjectionBinding, guard: Guard) -> tuple[dict, dict, dict]:
    """Bind exact input bytes and every transcript read by the existing compiler."""
    if not isinstance(binding, CaptionProjectionBinding) \
            or not _SHA.fullmatch(str(binding.execution_input_hash)) or not binding.dependencies:
        raise RuntimeError("held caption requires exact owner execution/pipeline bindings")
    refs = _unique((binding.plan, binding.manifest, binding.timeline, *binding.dependencies))
    verify_caption_files(refs, guard)
    plan, manifest, timeline = (read_caption_json(row, guard)
                               for row in (binding.plan, binding.manifest, binding.timeline))
    paths = {row.path for row in binding.dependencies}
    for source in manifest.get("sources", []):
        transcript = source.get("transcriptPath")
        if transcript and str(_transcript_path(transcript, binding)) not in paths:
            raise RuntimeError("held caption transcript lacks an independently held input reference")
    return plan, manifest, timeline


def _transcript_path(value: object, binding: CaptionProjectionBinding) -> Path:
    """Match the current compiler's sibling-manifest resolution without moving it."""
    if type(value) is not str or not value:
        raise RuntimeError("held caption transcript path is malformed")
    path = Path(value)
    return path if path.is_absolute() else Path(binding.manifest.path).parent / path


def _same_context(ctx: object, binding: CaptionProjectionBinding,
                  documents: tuple[dict, dict, dict]) -> RenderCaptionProjection:
    """Require the actual returned in-memory projection and unchanged caller inputs."""
    value = getattr(ctx, "caption_projection", None)
    if not isinstance(value, RenderCaptionProjection):
        raise RuntimeError("held caption capture needs the actual returned RenderCaptionProjection")
    plan, manifest, _timeline = documents
    actual = copy.deepcopy(getattr(ctx, "manifest", None))
    if isinstance(actual, dict) and "_path" not in manifest:
        if actual.pop("_path", None) != binding.manifest.path:
            raise RuntimeError("held caption render manifest path differs")
    if digest(getattr(ctx, "plan", None)) != digest(plan) or digest(actual) != digest(manifest) \
            or getattr(ctx, "plan_path", None) != binding.plan.path:
        raise RuntimeError("held caption render context differs from the held original inputs")
    return value


def _projection_data(value: RenderCaptionProjection) -> dict:
    """Detach mutable Python dictionaries; the returned data hash fences later edits."""
    return copy.deepcopy({"compilation": value.compilation, "authority": value.artifacts.receipt,
                          "shards": value.shards.manifest, "pages": value.pages.manifest})


def _artifact_paths(value: RenderCaptionProjection, root: Path) -> None:
    """Every returned projection path belongs to this exact ordinary render root."""
    expected = {"authority": "caption_authority.json", "compilation": "caption_compilation.json",
        "ass": "captions.ass", "srt": "captions.srt", "palmier": "caption_palmier.json", "shards": "caption_shards.json"}
    if "chapterProjection" in value.compilation:
        expected.update({"chapters_json": "caption_chapters.json", "chapters_text": "chapters.txt"})
    for key, name in expected.items():
        if getattr(value.artifacts, key, None) != str(root / name):
            raise RuntimeError("held caption returned artifact path differs")


def _document_refs(root: Path, data: dict, guard: Guard) -> tuple[CaptionFile, ...]:
    """Require exact named document bytes to represent the returned objects."""
    result = []
    for role, name in _DOCUMENTS.items():
        row = hold_caption_file(root / name, guard)
        if digest(read_caption_json(row, guard)) != digest(data[role]):
            raise RuntimeError("held caption returned projection differs from its exact disk document")
        result.append(row)
    return tuple(result)


def _named(root: Path, value: dict) -> CaptionFile:
    """Resolve only a basename from a closed held artifact reference."""
    if type(value) is not dict or set(value) != {"name", "sha256"} \
            or type(value["name"]) is not str or Path(value["name"]).name != value["name"] \
            or value["name"] in {"", ".", ".."} or not _SHA.fullmatch(str(value["sha256"])):
        raise RuntimeError("held caption artifact name/hash is malformed")
    path = root / value["name"]
    return CaptionFile(str(path), value["sha256"], path.lstat().st_size)


def _assets(root: Path, data: dict, guard: Guard) -> tuple[CaptionFile, ...]:
    """Capture all cue/page receipts, and exactly the authority's projected files."""
    rows = [_named(root, value) for value in data["authority"]["files"].values()]
    media = [entry["media"] for group in ("shards", "pages") for entry in data[group]["entries"]]
    rows.extend(_named(root, value) for value in media)
    receipts = {root / (value["name"] + ".json") for value in media}
    sizes = {Path(row.path): row.size_bytes for row in rows}
    sizes.update({path: path.lstat().st_size for path in receipts})
    if len(sizes) > MAX_FILES or sum(sizes.values()) > MAX_TOTAL_BYTES \
            or any(not 0 < size <= MAX_FILE_BYTES for size in sizes.values()) \
            or any(sizes[path] > MAX_JSON_BYTES for path in receipts):
        raise RuntimeError("held caption asset inventory exceeds preflight byte limits")
    for path in sorted(receipts):
        rows.append(hold_caption_file(path, guard, sizes[path]))
    return _unique(tuple(rows))


def _relations(held: HeldCaptionProjection, documents: tuple, guard: Guard) -> None:
    """Read only the exact retained inventory, never materialize or scan a cache."""
    plan, _manifest, timeline = documents
    identities = projection_identities(held.external)
    validate_projection(held.data, (plan, timeline), held.binding.frame_clock, identities["compiler"])
    by_name = {Path(row.path).name: row for row in held.files}
    read = lambda name: read_caption_json(by_name[name], guard)
    for entry in held.data["shards"]["entries"]:
        validate_shard_receipt(read(entry["media"]["name"] + ".json"), entry)
    guard()
    validate_pages(held.data, Path(held.root), (read, identities["tools"], identities["compositor"]))
    guard()


def _inventory(held: HeldCaptionProjection) -> None:
    """No omitted later media, unheld receipt, extra path or external relocation."""
    root, data = Path(held.root), held.data
    refs = list(data["authority"]["files"].values())
    media = [entry["media"] for group in ("shards", "pages") for entry in data[group]["entries"]]
    expected = set(_DOCUMENTS.values()) | {row["name"] for row in refs + media}
    expected.update(row["name"] + ".json" for row in media)
    by_name = {Path(row.path).name: row for row in held.files}
    if len(by_name) != len(held.files) or set(by_name) != expected \
            or any(Path(row.path).parent != root for row in held.files):
        raise RuntimeError("held caption local inventory is incomplete or relocated")
    for row in refs + media:
        if by_name[row["name"]].sha256 != row["sha256"]:
            raise RuntimeError("held caption media reference differs from returned projection")
    external = external_paths(data)
    if {row.path for row in held.external} != set(external):
        raise RuntimeError("held caption external inventory is incomplete or relocated")
    for row in held.external:
        if external[row.path] is not None and external[row.path] != row.sha256:
            raise RuntimeError("held caption external reference differs")


def capture_caption_projection(ctx: object, binding: CaptionProjectionBinding,
                               guard: Guard) -> HeldCaptionProjection:
    """Capture an actual return under owner-held bindings; never grant provenance."""
    documents = _binding(binding, guard)
    value = _same_context(ctx, binding, documents)
    root = Path(getattr(ctx, "out_dir"))
    real_directory(root)
    _artifact_paths(value, root)
    data = _projection_data(value)
    if Path(value.artifacts.authority) != root / _DOCUMENTS["authority"] \
            or binding.timeline.path != str(root / "timeline_map.json"):
        raise RuntimeError("held caption projection escaped its actual render output")
    validate_caption_shard_manifest(data["shards"])
    external = capture_external(data, guard)
    validate_projection(data, (documents[0], documents[2]), binding.frame_clock,
                        projection_identities(external)["compiler"])
    files = _unique((*_document_refs(root, data, guard), *_assets(root, data, guard)))
    held = HeldCaptionProjection(str(root), binding, data, digest(data), files, external)
    verify_caption_files(_unique((*held.files, *held.external)), guard)
    _relations(held, documents, guard)
    return read_caption_projection(held, binding, guard)


def read_caption_projection(held: HeldCaptionProjection, binding: CaptionProjectionBinding,
                            guard: Guard) -> HeldCaptionProjection:
    """Strong held-byte/lineage read, not source requalification or fresh execution."""
    if not isinstance(held, HeldCaptionProjection) or held.binding != binding \
            or held.data_hash != digest(held.data):
        raise RuntimeError("held caption original binding or returned projection changed")
    _inventory(held)
    documents = _binding(binding, guard)
    inventory = _unique((*held.files, *held.external))
    verify_caption_files(inventory, guard)
    _document_refs(Path(held.root), held.data, guard)
    _relations(held, documents, guard)
    verify_caption_files(inventory, guard)
    verify_caption_files(_unique((binding.plan, binding.manifest, binding.timeline, *binding.dependencies)), guard)
    guard()
    return held


def stage_caption_dependencies(held: HeldCaptionProjection, binding: CaptionProjectionBinding,
                               destination: Path, guard: Guard) -> tuple[CaptionFile, ...]:
    """New-only copies of the existing Audit B closure; no manifests/fonts/pages moved."""
    read_caption_projection(held, binding, guard)
    names = {value["name"] for value in held.data["authority"]["files"].values()}
    names.add("caption_authority.json")
    rows = tuple(row for row in held.files if Path(row.path).name in names)
    if len(rows) != len(names):
        raise RuntimeError("held caption Audit B dependency inventory is incomplete")
    staged = stage_caption_files(rows, destination, guard)
    read_caption_projection(held, binding, guard)
    return staged
