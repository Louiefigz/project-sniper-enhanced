"""Closed clip bindings for deterministic headless MP4 composition.

The manifest deliberately carries no paths.  A trusted adapter resolves the
two bound artifact digests after this contract proves timing and placement
against an approved plan and its ordered graphic assets.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from .quality_pass_contract import (
    GraphicAssetRefV1,
    QualityPassContractError,
    graphic_render_intent_digest,
    validate_graphic_asset,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_ROW_KEYS = {
    "anchor",
    "graphicId",
    "mediaSha256",
    "outEnd",
    "outStart",
    "renderReceiptSha256",
    "x",
    "y",
}
_GRAPH_EFFECT_KEYS = {"exitOnCut", "pipHole", "takeoverBase"}


class PreboundClipContractError(RuntimeError):
    """A clip manifest is malformed, ambiguous, or not plan-bound."""


@dataclass(frozen=True)
class PreboundClipV1:
    """One immutable, path-free compositor input binding."""

    graphic_id: str
    out_start: int | float
    out_end: int | float
    anchor: str
    x: int | float
    y: int | float
    media_sha256: str
    render_receipt_sha256: str
    row_json: bytes


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PreboundClipContractError(
            "prebound clip JSON is not canonical") from exc
    return encoded.encode("ascii")


def _number(label: str, value: object) -> int | float:
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        finite = False
    valid = type(value) in {int, float} and finite
    if not valid:
        raise PreboundClipContractError(f"{label} must be a finite number")
    return value


def _row_values(row: object) -> tuple:
    if type(row) is not dict or set(row) != _ROW_KEYS:
        raise PreboundClipContractError("prebound clip row keys are invalid")
    graphic_id = row["graphicId"]
    digests = (row["mediaSha256"], row["renderReceiptSha256"])
    valid = (
        type(graphic_id) is str
        and bool(_GRAPHIC_ID.fullmatch(graphic_id))
        and row["anchor"] == "free-band"
        and all(type(item) is str and _DIGEST.fullmatch(item)
                for item in digests)
    )
    if not valid:
        raise PreboundClipContractError("prebound clip identity is invalid")
    start = _number("outStart", row["outStart"])
    end = _number("outEnd", row["outEnd"])
    x = _number("x", row["x"])
    y = _number("y", row["y"])
    if start < 0 or end <= start:
        raise PreboundClipContractError("prebound clip window is invalid")
    return graphic_id, start, end, row["anchor"], x, y, *digests


def _parse_row(row: object) -> PreboundClipV1:
    values = _row_values(row)
    return PreboundClipV1(*values, _canonical(row))


def _same_clip(first: PreboundClipV1, second: PreboundClipV1) -> bool:
    names = tuple(PreboundClipV1.__dataclass_fields__)
    return all(type(getattr(first, name)) is type(getattr(second, name))
               and getattr(first, name) == getattr(second, name)
               for name in names)


def _validated_clips(value: object) -> tuple[PreboundClipV1, ...]:
    if type(value) is not tuple or not value:
        raise PreboundClipContractError(
            "prebound clip set must be a nonempty tuple")
    for clip in value:
        if type(clip) is not PreboundClipV1 or type(clip.row_json) is not bytes:
            raise PreboundClipContractError("prebound clip instance is invalid")
        try:
            row = json.loads(clip.row_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PreboundClipContractError(
                "prebound clip row bytes are invalid") from exc
        if (_canonical(row) != clip.row_json
                or not _same_clip(_parse_row(row), clip)):
            raise PreboundClipContractError(
                "prebound clip row identity is invalid")
    ids = tuple(clip.graphic_id for clip in value)
    if len(ids) != len(set(ids)):
        raise PreboundClipContractError("prebound graphic IDs are duplicated")
    return value


def parse_prebound_clips(document_json: bytes) -> tuple[PreboundClipV1, ...]:
    """Parse an ordered manifest from exact canonical JSON bytes."""
    if type(document_json) is not bytes:
        raise PreboundClipContractError(
            "prebound clip document must be immutable bytes")
    try:
        rows = json.loads(document_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreboundClipContractError(
            "prebound clip document bytes are invalid") from exc
    if type(rows) is not list or not rows:
        raise PreboundClipContractError(
            "prebound clip document must be a nonempty array")
    if _canonical(rows) != document_json:
        raise PreboundClipContractError(
            "prebound clip document is not exact canonical JSON")
    return _validated_clips(tuple(_parse_row(row) for row in rows))


def _plan_row_values(row: object) -> tuple:
    if type(row) is not dict or any(key in row for key in _GRAPH_EFFECT_KEYS):
        raise PreboundClipContractError("R0 plan graphic effects are unsupported")
    placement = row.get("placement")
    valid = (
        isinstance(row.get("id"), str)
        and bool(_GRAPHIC_ID.fullmatch(row["id"]))
        and row.get("kind") == "section-marker"
        and row.get("anchor") == "free-band"
        and type(placement) is dict
        and set(placement) == {"x", "y"}
    )
    if not valid:
        raise PreboundClipContractError(
            "R0 requires a placed free-band section marker")
    start = _number("plan outStart", row.get("outStart"))
    end = _number("plan outEnd", row.get("outEnd"))
    x = _number("plan placement.x", placement["x"])
    y = _number("plan placement.y", placement["y"])
    if start < 0 or end <= start:
        raise PreboundClipContractError("R0 plan graphic window is invalid")
    return row["id"], start, end, row["anchor"], x, y


def _validated_plan_rows(plan: object) -> tuple[dict, ...]:
    if type(plan) is not dict or type(plan.get("graphicsTrack")) is not list:
        raise PreboundClipContractError("approved graphics track is invalid")
    rows = tuple(plan["graphicsTrack"])
    if not rows:
        raise PreboundClipContractError("approved graphics track is empty")
    identities = tuple(_plan_row_values(row)[0] for row in rows)
    if len(identities) != len(set(identities)):
        raise PreboundClipContractError("approved graphic IDs are duplicated")
    return rows


def _validate_asset(row: dict, clip: PreboundClipV1,
                    asset: GraphicAssetRefV1) -> None:
    try:
        validate_graphic_asset(asset)
        render_intent = graphic_render_intent_digest(row)
    except (QualityPassContractError, TypeError, ValueError) as exc:
        raise PreboundClipContractError(str(exc)) from exc
    expected = (
        clip.graphic_id,
        clip.media_sha256,
        clip.render_receipt_sha256,
        render_intent,
    )
    actual = (
        asset.graphic_id,
        asset.media.artifact.sha256,
        asset.receipt.sha256,
        asset.render_intent_digest,
    )
    if actual != expected:
        raise PreboundClipContractError(
            "prebound clip does not match its graphic asset")


def _validate_binding(row: dict, clip: PreboundClipV1,
                      asset: GraphicAssetRefV1) -> None:
    identity, start, end, anchor, x, y = _plan_row_values(row)
    actual = (clip.graphic_id, clip.out_start, clip.out_end,
              clip.anchor, clip.x, clip.y)
    if actual != (identity, start, end, anchor, x, y):
        raise PreboundClipContractError(
            "prebound clip timing or placement differs from plan")
    _validate_asset(row, clip, asset)


def validate_prebound_clips(clips: object, plan: object,
                            assets: object) -> None:
    """Prove ordered clips against a plan and sealed assets; admit R0 only."""
    bound = _validated_clips(clips)
    rows = _validated_plan_rows(plan)
    counts_match = (type(assets) is tuple
                    and len(bound) == len(rows) == len(assets))
    if not counts_match:
        raise PreboundClipContractError(
            "clip, plan, and asset counts do not exactly match")
    clip_ids = tuple(clip.graphic_id for clip in bound)
    plan_ids = tuple(row["id"] for row in rows)
    asset_ids = tuple(getattr(asset, "graphic_id", None) for asset in assets)
    if clip_ids != plan_ids or asset_ids != plan_ids:
        raise PreboundClipContractError(
            "clip, plan, and asset order does not exactly match")
    for row, clip, asset in zip(rows, bound, assets):
        _validate_binding(row, clip, asset)
    if len(bound) != 1:
        raise PreboundClipContractError(
            "R0 prebound composition requires exactly one graphic")


def prebound_clip_set_digest(clips: object) -> str:
    """Return the domain-separated identity of the exact ordered clip set."""
    bound = _validated_clips(clips)
    raw = b"[" + b",".join(clip.row_json for clip in bound) + b"]"
    return hashlib.sha256(b"sniper-prebound-clip-set-v1\0" + raw).hexdigest()
