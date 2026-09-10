"""Immutable asset identity and publication-rights gates for motion scenes."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_MAX_BYTES = 1024 ** 3
_ROOT_KEYS = {
    "schemaVersion", "assetId", "sha256", "sizeBytes", "mime", "origin",
    "acquiredAt", "rights", "media", "provenance", "publicationDisposition",
}
_RIGHTS_KEYS = {
    "license", "allowedUses", "allowedPlatforms", "consent",
    "attributionRequired", "attribution", "expiresAt",
}
_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/svg+xml", "audio/wav",
    "audio/mpeg", "video/mp4", "video/quicktime", "font/ttf", "font/otf",
}
_ORIGINS = {
    "operator-upload", "approved-library", "generated", "reference-derived",
}
_USES = {"editorial", "commercial", "thumbnail", "cover", "loop"}
_PLATFORMS = {
    "youtube", "instagram", "linkedin", "tiktok", "facebook", "local-review",
}


class AssetGovernanceError(ValueError):
    """An asset cannot enter or remain in a publishable scene."""


@dataclass(frozen=True)
class AssetAdmission:
    """Stable binding emitted after byte identity and rights pass."""

    asset_id: str
    sha256: str
    size_bytes: int
    mime: str
    attribution: str | None


@dataclass(frozen=True)
class AssetUse:
    """One destination-specific rights evaluation."""

    use: str
    platform: str
    now: datetime | None = None


def _strict_object(value: object, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict):
        raise AssetGovernanceError(f"{label} must be an object")
    extras = sorted(set(value) - keys)
    if extras:
        raise AssetGovernanceError(f"{label} has unsupported fields: {extras}")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise AssetGovernanceError(f"{label} must be an RFC3339 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AssetGovernanceError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise AssetGovernanceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _string_list(value: object, label: str, allowed: set[str]) -> list[str]:
    valid = isinstance(value, list) and value \
        and len(set(value)) == len(value) \
        and all(isinstance(item, str) and item in allowed for item in value)
    if not valid:
        raise AssetGovernanceError(f"{label} is invalid")
    return value


def _media(value: object) -> None:
    row = _strict_object(value, "asset.media", {
        "width", "height", "durationFrames", "sampleRate", "channels",
        "hasAlpha", "colorSpace",
    })
    bounds = {
        "width": (1, 16384), "height": (1, 16384),
        "durationFrames": (1, 10 ** 9), "sampleRate": (8000, 384000),
        "channels": (1, 32),
    }
    for key, limits in bounds.items():
        if key in row and (type(row[key]) is not int
                           or not limits[0] <= row[key] <= limits[1]):
            raise AssetGovernanceError(f"asset.media.{key} is invalid")
    if "hasAlpha" in row and type(row["hasAlpha"]) is not bool:
        raise AssetGovernanceError("asset.media.hasAlpha must be boolean")
    if "colorSpace" in row and (
            not isinstance(row["colorSpace"], str)
            or not 0 < len(row["colorSpace"]) <= 80):
        raise AssetGovernanceError("asset.media.colorSpace is invalid")


def _provenance(value: object, origin: str) -> None:
    row = _strict_object(value, "asset.provenance", {"source", "generator"})
    if not isinstance(row.get("source"), str) or not row["source"].strip():
        raise AssetGovernanceError("asset.provenance.source is required")
    generator = row.get("generator")
    if origin == "generated" and generator is None:
        raise AssetGovernanceError("generated asset needs generator provenance")
    if generator is None:
        return
    item = _strict_object(
        generator, "asset.provenance.generator",
        {"model", "version", "requestHash"})
    if set(item) != {"model", "version", "requestHash"} \
            or not all(isinstance(item[key], str) and item[key].strip()
                       for key in ("model", "version")) \
            or not isinstance(item["requestHash"], str) \
            or not _SHA256.fullmatch(item["requestHash"]):
        raise AssetGovernanceError("asset generator provenance is invalid")


def _record_shape(record: object) -> dict:
    row = _strict_object(record, "asset", _ROOT_KEYS)
    missing = sorted(_ROOT_KEYS - set(row))
    if missing:
        raise AssetGovernanceError(f"asset is missing fields: {missing}")
    if row["schemaVersion"] != 1:
        raise AssetGovernanceError("asset.schemaVersion must be 1")
    if not isinstance(row["assetId"], str) or not _ID.fullmatch(row["assetId"]):
        raise AssetGovernanceError("asset.assetId must be a stable id")
    if not isinstance(row["sha256"], str) or not _SHA256.fullmatch(row["sha256"]):
        raise AssetGovernanceError("asset.sha256 must be lowercase SHA-256")
    size = row["sizeBytes"]
    if isinstance(size, bool) or not isinstance(size, int) \
            or not 0 < size <= _MAX_BYTES:
        raise AssetGovernanceError("asset.sizeBytes is outside the released bound")
    if row["mime"] not in _MIMES:
        raise AssetGovernanceError("asset.mime is unsupported")
    if row["origin"] not in _ORIGINS:
        raise AssetGovernanceError("asset.origin is unsupported")
    _timestamp(row["acquiredAt"], "asset.acquiredAt")
    if row["publicationDisposition"] not in {
            "approved", "blocked", "expired", "needs-review"}:
        raise AssetGovernanceError("asset publication disposition is unsupported")
    _media(row["media"])
    _provenance(row["provenance"], row["origin"])
    return row


def _rights(record: dict, use: str, platform: str, now: datetime) -> str | None:
    rights = _strict_object(record["rights"], "asset.rights", _RIGHTS_KEYS)
    required = {"license", "allowedUses", "allowedPlatforms", "consent",
                "attributionRequired"}
    if missing := sorted(required - set(rights)):
        raise AssetGovernanceError(f"asset.rights is missing fields: {missing}")
    if not isinstance(rights["license"], str) or not rights["license"].strip():
        raise AssetGovernanceError("asset.rights.license is required")
    allowed_uses = _string_list(
        rights["allowedUses"], "asset.rights.allowedUses", _USES)
    allowed_platforms = _string_list(
        rights["allowedPlatforms"], "asset.rights.allowedPlatforms", _PLATFORMS)
    if use not in allowed_uses or platform not in allowed_platforms:
        raise AssetGovernanceError("asset rights do not allow this use/platform")
    if rights["consent"] not in {
            "not-applicable", "verified", "missing", "unknown"}:
        raise AssetGovernanceError("asset consent is invalid")
    if rights["consent"] in {"missing", "unknown"}:
        raise AssetGovernanceError("asset consent is not verified")
    if type(rights["attributionRequired"]) is not bool:
        raise AssetGovernanceError("asset attributionRequired must be boolean")
    if "expiresAt" in rights and _timestamp(
            rights["expiresAt"], "asset.rights.expiresAt") <= now:
        raise AssetGovernanceError("asset rights have expired")
    attribution = rights.get("attribution")
    if rights["attributionRequired"] and (
            not isinstance(attribution, str) or not attribution.strip()):
        raise AssetGovernanceError("required asset attribution is missing")
    return attribution if isinstance(attribution, str) else None


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_asset(path: str) -> tuple[BinaryIO, os.stat_result]:
    if not os.path.isabs(path) or os.path.normpath(path) != path \
            or os.path.realpath(path) != path:
        raise AssetGovernanceError("asset path must be canonical and absolute")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AssetGovernanceError("asset could not be opened safely") from exc
    handle = os.fdopen(fd, "rb")
    info = os.fstat(fd)
    valid = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and info.st_uid == os.geteuid() and 0 < info.st_size <= _MAX_BYTES)
    if not valid:
        handle.close()
        raise AssetGovernanceError("asset must be one owned bounded regular file")
    return handle, info


def _hash_and_prefix(handle: BinaryIO) -> tuple[str, bytes, bool]:
    digest = hashlib.sha256()
    prefix = b""
    tail = b""
    unsafe_svg = False
    denied = (
        b"<!entity", b"<script", b"javascript:", b"onload=", b"onerror=",
        b"<foreignobject",
    )
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            return digest.hexdigest(), prefix, unsafe_svg
        if len(prefix) < 4096:
            prefix += chunk[:4096 - len(prefix)]
        lowered = (tail + chunk).lower()
        unsafe_svg = unsafe_svg or any(marker in lowered for marker in denied)
        remote = lowered.replace(
            b"http://www.w3.org/2000/svg", b"").replace(
                b"http://www.w3.org/1999/xlink", b"")
        unsafe_svg = unsafe_svg or b"http://" in remote or b"https://" in remote
        tail = lowered[-32:]
        digest.update(chunk)


def _looks_like(mime: str, prefix: bytes, unsafe_svg: bool) -> bool:
    stripped = prefix.lstrip()
    if mime == "image/png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return prefix.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    if mime == "image/svg+xml":
        return b"<svg" in stripped[:1024].lower() and not unsafe_svg
    if mime == "audio/wav":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE"
    if mime == "audio/mpeg":
        return prefix.startswith(b"ID3") or prefix[:2] in {
            b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
    if mime in {"video/mp4", "video/quicktime"}:
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"
    if mime == "font/ttf":
        return prefix.startswith((b"\x00\x01\x00\x00", b"true", b"ttcf"))
    if mime == "font/otf":
        return prefix.startswith(b"OTTO")
    return False


def admit_asset(record: object, path: str, context: AssetUse) -> AssetAdmission:
    """Bind exact bytes to a currently publishable AssetRecordV1."""
    row = _record_shape(record)
    if row["publicationDisposition"] != "approved":
        raise AssetGovernanceError("asset is not approved for publication")
    current = (context.now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attribution = _rights(row, context.use, context.platform, current)
    handle, before = _open_asset(path)
    try:
        digest, prefix, unsafe_svg = _hash_and_prefix(handle)
        after = os.fstat(handle.fileno())
    finally:
        handle.close()
    if _file_identity(before) != _file_identity(after) \
            or _file_identity(after) != _file_identity(
                os.stat(path, follow_symlinks=False)):
        raise AssetGovernanceError("asset changed while being admitted")
    if after.st_size != row["sizeBytes"] or digest != row["sha256"]:
        raise AssetGovernanceError("asset bytes do not match AssetRecordV1")
    if not _looks_like(row["mime"], prefix, unsafe_svg):
        raise AssetGovernanceError("asset MIME disagrees with its bytes")
    return AssetAdmission(row["assetId"], digest, after.st_size, row["mime"],
                          attribution)
