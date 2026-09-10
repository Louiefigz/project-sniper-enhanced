"""Closed receipt semantics for program-audio channel normalization."""
from __future__ import annotations

import math

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.picture_lock_common import content_hash

# Integral JSON numbers survive the Python -> TypeScript -> Python authority
# round trip without changing canonical identity.
DEAD_CHANNEL_FLOOR_DB = -50
DEAD_CHANNEL_DELTA_DB = 25


class ChannelReceiptError(ValueError):
    """A channel-normalization receipt is invalid or has drifted."""


def peak_token(value: float) -> str:
    """Encode finite peaks and digital silence as strict JSON strings."""
    return "negative-infinity" if not math.isfinite(value) \
        else f"{value:.6f}"


def _dead_channel(peaks: list[float]) -> tuple[int | None, int | None]:
    for candidate_dead, candidate_live in ((0, 1), (1, 0)):
        low, high = peaks[candidate_dead], peaks[candidate_live]
        if low < DEAD_CHANNEL_FLOOR_DB <= high \
                and high - low >= DEAD_CHANNEL_DELTA_DB:
            return candidate_dead, candidate_live
    return None, None


def _filters(channels: int, live: int | None) -> tuple[str, str, str]:
    if live is not None:
        return (
            "dead-channel-repaired",
            f"pan=stereo|c0=c{live}|c1=c{live}",
            f"pan=mono|c0=c{live}",
        )
    if channels == 1:
        return "mono-duplicated", "pan=stereo|c0=c0|c1=c0", "anull"
    if channels == 2:
        return (
            "stereo-verified",
            "aformat=channel_layouts=stereo",
            "aformat=channel_layouts=mono",
        )
    return (
        "multichannel-downmixed",
        "aformat=channel_layouts=stereo",
        "aformat=channel_layouts=mono",
    )


def decision(channels: int, peaks: list[float]) -> dict[str, object]:
    """Derive the only legal target filters from observed channel peaks."""
    dead, live = _dead_channel(peaks) if channels == 2 else (None, None)
    status, stereo, mono = _filters(channels, live)
    return {
        "status": status, "deadChannel": dead, "liveChannel": live,
        "floorDb": DEAD_CHANNEL_FLOOR_DB,
        "minimumDeltaDb": DEAD_CHANNEL_DELTA_DB,
        "stereoFilter": stereo, "monoFilter": mono,
    }


def seal_channel_receipt(body: dict[str, object]) -> dict:
    """Self-hash and verify one receipt body."""
    return verify_channel_receipt(
        {**body, "receiptHash": content_hash(body)})


def verify_channel_receipt(value: object) -> dict:
    """Validate the closed schema, self-hash, and filter/status semantics."""
    try:
        receipt = validate_document(
            "channel-normalization-receipt-v1.schema.json", value)
    except SchemaValidationError as exc:
        raise ChannelReceiptError(
            "channel-normalization receipt violates its schema") from exc
    body = {key: item for key, item in receipt.items()
            if key != "receiptHash"}
    if receipt["receiptHash"] != content_hash(body):
        raise ChannelReceiptError(
            "channel-normalization receipt hash drifted")
    expected = decision(
        receipt["stream"]["channels"],
        [(-math.inf if token == "negative-infinity" else float(token))
         for token in receipt["stream"]["peakDbfs"]])
    if receipt["decision"] != expected:
        raise ChannelReceiptError(
            "channel-normalization decision is not reproducible")
    return receipt
