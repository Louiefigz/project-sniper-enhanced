"""Closed original-worker observation projections, never fresh decoded evidence.

The enclosing stopped-worker reader must authenticate the raw receipt and its
implementation before calling this module. Probe stdout is represented only by
its original attested hashes; no live observation or execution owner is rebuilt.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, fields

from graphics.presenter_layout_graph import PresenterGraphAsset
from guided_opening_inputs import closed, hash_value
from guided_presenter_assets import SelectedPresenterAsset
from guided_presenter_capture_inputs import PresenterCaptureSelection
from guided_presenter_observation import ObservedPresenterAsset, _command_hash, _commands
from guided_presenter_png import PresenterPngMetadata, validate_presenter_png_metadata
from guided_presenter_probe_contract import canonical_presenter_rate
from guided_presenter_probe_identity import HeldPresenterProbeFile, _validate_reference
from opening_prefix_contract import canonical_hash
from opening_prefix_graphs import bounded_graph_json
from opening_prefix_presenter import _file_record, _png_record

_KEYS = {"policy", "scope", "source", "ffprobe", "graphAsset", "admissionHash",
         "requestedFrameRate", "graphFrameRate", "headerSha256", "framesSha256",
         "commands", "commandSha256", "pngMetadata"}
_PNG_KEYS = {"width", "height", "color_chunks", "chunks", "metadata_bytes_read",
             "metadataEncoding", "metadata"}


def _png_payload(row: object) -> tuple[str, bytes]:
    """Reject noncanonical/oversized hex before allocating retained metadata bytes."""
    if type(row) is not list or len(row) != 2 or type(row[0]) is not str or type(row[1]) is not str:
        raise RuntimeError("presenter read PNG metadata pair is malformed")
    raw = row[1]
    if len(raw) > 2 * 1024 * 1024 or len(raw) % 2 or any(char not in "0123456789abcdef" for char in raw):
        raise RuntimeError("presenter read PNG metadata is not bounded canonical hex")
    return row[0], bytes.fromhex(raw)


def _png(value: object, asset: PresenterGraphAsset, size: int) -> None:
    """Check original byte-bound metadata only; neither IDAT nor pixels are read."""
    if asset.kind != "still-image":
        if value is not None:
            raise RuntimeError("presenter video has transplanted PNG attestations")
        return
    row = closed(value, _PNG_KEYS, "presenter read PNG observation")
    if row["metadataEncoding"] != "hex" or type(row["metadata"]) is not list or len(row["metadata"]) > 9 \
            or type(row["chunks"]) is not list or not 1 <= len(row["chunks"]) <= 4096 \
            or any(type(item) is not list or len(item) != 3 for item in row["chunks"]) \
            or type(row["color_chunks"]) is not list \
            or any(type(row[key]) is not int for key in ("width", "height", "metadata_bytes_read")):
        raise RuntimeError("presenter read PNG inventory is malformed")
    metadata = PresenterPngMetadata(row["width"], row["height"], tuple(row["color_chunks"]),
        tuple(tuple(item) for item in row["chunks"]), row["metadata_bytes_read"],
        tuple(_png_payload(item) for item in row["metadata"]))
    validate_presenter_png_metadata(metadata, size)
    if (metadata.width, metadata.height) != (asset.width, asset.height) \
            or canonical_hash(_png_record(metadata)) != canonical_hash(row):
        raise RuntimeError("presenter read PNG projection differs from original graph metadata")


def _file(value: object, expected: HeldPresenterProbeFile, tool: bool) -> None:
    """Compare to independently held identities, not a late stat plus claimed hash."""
    _validate_reference(expected, tool)
    row = closed(value, {"path", "sha256", "size_bytes", "statIdentityEncoding", "stat_identity"},
                 "presenter read held file")
    # Exact decimal strings reject rounding/noncanonical spelling, numeric
    # booleans and any reordered or substituted inode/timestamp value.
    if canonical_hash(row) != canonical_hash(_file_record(expected)):
        raise RuntimeError("presenter read file differs from independently held source/tool identity")


def _metadata(row: dict, selected: SelectedPresenterAsset, rate: str) -> PresenterGraphAsset:
    """Parse graph metadata as data, then bind kind/ID/path to selected admission."""
    admission = selected.admission
    payload = closed(row["graphAsset"], {field.name for field in fields(PresenterGraphAsset)}, "presenter read graph asset")
    asset = PresenterGraphAsset(**payload)
    kind = "still-image" if admission.media_kind == "still-image" else "video"
    if (asset.asset_id, asset.path, asset.kind) != (admission.asset_id, admission.snapshot_path, kind) \
            or row["admissionHash"] != canonical_hash(asdict(admission)) \
            or row["requestedFrameRate"] != rate or row["graphFrameRate"] != canonical_presenter_rate(rate):
        raise RuntimeError("presenter read graph asset/admission/frame clock differs")
    _png(row["pngMetadata"], asset, admission.source_size_bytes)
    return asset


def _commands_match(row: dict, selected: SelectedPresenterAsset, tool: HeldPresenterProbeFile) -> None:
    """Reconstruct exact argv as inert data; stdout hashes remain worker attestations."""
    expected = _commands(selected.admission.snapshot_path, tool.path, selected.admission.media_kind)
    if canonical_hash(row["commands"]) != canonical_hash([list(command) for command in expected]) \
            or row["commandSha256"] != [_command_hash(command) for command in expected]:
        raise RuntimeError("presenter read observation commands differ from held source/tool")
    hash_value(row["headerSha256"])
    hash_value(row["framesSha256"])


def read_observation_records(records: object, selection: PresenterCaptureSelection,
                             tool: HeldPresenterProbeFile, guard: Callable[[], None]) -> dict[str, PresenterGraphAsset]:
    """Validate bounded original attestations without source reads or a fresh decode."""
    if not callable(guard) or type(records) is not list or not 1 <= len(records) <= 32:
        raise RuntimeError("presenter read requires bounded original observation attestations")
    selected = {row.admission.asset_id: row for row in reversed(selection.selected)}
    sources = {row.path: row for row in selection.sources}
    result, paths = {}, set()
    for record in records:
        guard()
        bounded_graph_json(record)
        row = closed(record, _KEYS, "presenter read observation")
        asset_id = row["graphAsset"].get("asset_id") if type(row["graphAsset"]) is dict else None
        if type(asset_id) is not str or asset_id not in selected or asset_id in result:
            raise RuntimeError("presenter read observation IDs are missing, extra or duplicated")
        item = selected[asset_id]
        if row["policy"] != ObservedPresenterAsset.policy or row["scope"] != ObservedPresenterAsset.scope:
            raise RuntimeError("presenter read observation policy/scope differs")
        _file(row["source"], sources[item.admission.snapshot_path], False)
        _file(row["ffprobe"], tool, True)
        _commands_match(row, item, tool)
        asset = _metadata(row, item, selection.frame_rate)
        if asset.path in paths:
            raise RuntimeError("presenter read observation source paths are ambiguous")
        result[asset_id] = asset
        paths.add(asset.path)
    if set(result) != set(selected):
        raise RuntimeError("presenter read observations do not cover all original windows")
    guard()
    return result
