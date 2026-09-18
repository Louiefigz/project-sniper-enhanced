"""Fail-closed static contract for a live Palmier acceptance worklist."""
from __future__ import annotations

import os
import re

from fingerprints import file_sha256
from palmier.desktop_native_captions import (
    MCP_CAPTION_KEYS, REQUIRED_KEYS, validate_native_caption_settings)
from palmier.desktop_caption_shard_plan import FULL_CANVAS_TRANSFORM
from palmier.mcp_client import PalmierError

PASSIVE_OPS = {"warn", "native-audio-review"}
SUPPORTED_OPS = PASSIVE_OPS | {
    "import", "overlays", "replace-overlay", "baseline", "keyframes", "text",
    "native-broll", "native-music", "native-captions", "native-denoise",
    "native-color", "exact-master-reference-add",
    "exact-master-reference-disable", "native-audio-master",
    "mastered-stereo-route", "caption-alpha-shard", "title-alpha-shard",
    "graphics-alpha-shard",
    "caption-alpha-pages",
}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def validate_steps(steps: list, stage: object) -> None:
    """Reject the whole worklist before the first live mutation."""
    malformed = [row for row in steps if not isinstance(row, dict)
                 or row.get("op") not in SUPPORTED_OPS]
    if malformed:
        op = malformed[0].get("op") if isinstance(malformed[0], dict) else None
        raise PalmierError(f"live acceptance cannot execute worklist op {op!r}")
    for row in steps:
        _validate_step(row)
    _validate_resource_order(steps)
    if stage == "visual":
        _require_sequence(steps, (
            "exact-master-reference-add",
            "exact-master-reference-disable",
            "native-audio-master", "mastered-stereo-route"))
        exact_imports = [row for row in steps if row.get("op") == "import"
                         and row.get("key") == "exact-master-reference"]
        if len(exact_imports) != 1:
            raise PalmierError(
                "visual acceptance requires one exact-master import")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PalmierError(f"live acceptance {label} is missing")
    return value


def _frames(row: dict) -> None:
    start, end = row.get("startFrame"), row.get("endFrame")
    valid = all(isinstance(value, int) and not isinstance(value, bool)
                for value in (start, end))
    if not valid or start < 0 or end <= start:
        raise PalmierError(
            f"live acceptance {row.get('op')} frame window is malformed")


def _asset(row: dict, path_key: str = "path",
           hash_key: str = "fileHash") -> None:
    path, digest = row.get(path_key), row.get(hash_key)
    valid = isinstance(path, str) and os.path.isabs(path) \
        and os.path.isfile(path) and not os.path.islink(path) \
        and isinstance(digest, str) and _SHA.fullmatch(digest) \
        and file_sha256(path) == digest
    if not valid:
        raise PalmierError(
            f"live acceptance {row.get('op')} media authority changed")


def _native_media(row: dict) -> None:
    _frames(row)
    _asset(row)
    _string(row.get("elementId"), f"{row.get('op')} elementId")


def _validate_overlay(row: dict) -> None:
    entries = row.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PalmierError("live acceptance overlays are empty")
    for entry in entries:
        if not isinstance(entry, dict):
            raise PalmierError("live acceptance overlay entry is malformed")
        _frames(entry)
        _string(entry.get("mediaKey"), "overlay mediaKey")
        _string(entry.get("elementId"), "overlay elementId")
        _asset(entry, "assetPath", "assetHash")


def _validate_step(row: dict) -> None:
    op = row["op"]
    if op == "import":
        _string(row.get("key"), "import key")
        _asset(row)
    elif op == "overlays":
        _validate_overlay(row)
    elif op == "replace-overlay":
        _native_media(row)
        _string(row.get("oldClipId"), "replacement oldClipId")
        index = row.get("trackIndex")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise PalmierError("live acceptance replacement track is malformed")
    elif op in {"native-broll", "native-music", "native-audio-master"}:
        _native_media(row)
        if op == "native-broll" and (
                row.get("trackPolicy") != "new-top-video-track-per-broll"
                or row.get("transform") != FULL_CANVAS_TRANSFORM
                or row.get("focusOps")):
            raise PalmierError(
                "live acceptance native-broll track policy is malformed")
    elif op in {
            "caption-alpha-shard", "title-alpha-shard",
            "graphics-alpha-shard"}:
        _frames(row)
        _string(row.get("elementId"), f"{op} elementId")
        _string(row.get("mediaKey"), f"{op} mediaKey")
        _asset(row, "assetPath", "assetHash")
        policies = {
            "caption-alpha-shard": "new-top-video-track-per-cue",
            "title-alpha-shard": "new-top-video-track-per-card",
            "graphics-alpha-shard": "new-top-video-track-per-graphic",
        }
        alpha_invalid = (
            row.get("alphaMode") != "straight"
            and op != "graphics-alpha-shard")
        if alpha_invalid or row.get("trackPolicy") != policies[op] \
                or row.get("transform") != FULL_CANVAS_TRANSFORM:
            raise PalmierError(
                f"live acceptance {op} policy is malformed")
    elif op == "caption-alpha-pages":
        entries = row.get("entries")
        if not isinstance(entries, list) or not entries:
            raise PalmierError("live acceptance caption pages are empty")
        if row.get("trackPolicy") \
                != "one-new-top-video-track-for-all-pages":
            raise PalmierError("live acceptance caption page policy is malformed")
        for entry in entries:
            _frames(entry)
            _string(entry.get("elementId"), "caption page elementId")
            _string(entry.get("mediaKey"), "caption page mediaKey")
            _asset(entry, "assetPath", "assetHash")
            if entry.get("transform") != FULL_CANVAS_TRANSFORM:
                raise PalmierError(
                    "live acceptance caption page transform is malformed")
    elif op in {"text", "exact-master-reference-add"}:
        _frames(row)
        if op == "text":
            _string(row.get("content"), "text content")
        else:
            _string(row.get("mediaKey"), "exact-master mediaKey")
            _asset(row, "assetPath", "assetHash")
    elif op == "native-captions":
        _validate_caption_settings(row.get("settings"))
    elif op in {"native-denoise", "native-color"}:
        if not isinstance(row.get("settings"), dict):
            raise PalmierError(f"live acceptance {op} settings are malformed")
    elif op == "baseline" and not isinstance(row.get("transform"), dict):
        raise PalmierError("live acceptance baseline transform is malformed")
    elif op == "keyframes":
        _string(row.get("property"), "keyframe property")
        if not isinstance(row.get("clip"), int) \
                or isinstance(row["clip"], bool) \
                or not isinstance(row.get("rows"), list) or not row["rows"]:
            raise PalmierError("live acceptance keyframe step is malformed")


def _validate_resource_order(steps: list[dict]) -> None:
    imported: dict[str, dict] = {}
    for row in steps:
        if row["op"] == "import":
            key = row["key"]
            if key in imported:
                raise PalmierError(f"live acceptance repeats import key {key!r}")
            imported[key] = row
            continue
        entries = row.get("entries") \
            if row["op"] in {"overlays", "caption-alpha-pages"} else [row]
        if row["op"] not in {
                "overlays", "replace-overlay",
                "exact-master-reference-add", "caption-alpha-shard",
                "title-alpha-shard", "graphics-alpha-shard",
                "caption-alpha-pages"}:
            continue
        for entry in entries:
            key = entry.get("mediaKey")
            match = imported.get(key) if isinstance(key, str) else None
            if row["op"] == "replace-overlay":
                match = next((value for value in imported.values()
                              if value.get("fileHash") == row.get("fileHash")
                              and value.get("elementId")
                              == row.get("elementId")), None)
            if not isinstance(match, dict):
                raise PalmierError(
                    f"live acceptance {row['op']} precedes its bound import")


def _validate_caption_settings(value: object) -> None:
    settings = validate_native_caption_settings(value)
    if set(settings) - MCP_CAPTION_KEYS or REQUIRED_KEYS - set(settings):
        raise PalmierError("native caption settings differ from MCP vocabulary")


def _require_sequence(steps: list[dict], expected: tuple[str, ...]) -> None:
    positions = []
    for op in expected:
        matches = [index for index, row in enumerate(steps)
                   if row.get("op") == op]
        if len(matches) != 1:
            raise PalmierError(f"visual acceptance requires exactly one {op}")
        positions.append(matches[0])
    if positions != sorted(positions):
        raise PalmierError("exact-master/mastered-stereo worklist order is unsafe")
