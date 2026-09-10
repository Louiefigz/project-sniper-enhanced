#!/usr/bin/env python3
"""Resolve and bind every local font byte used by caption alpha rendering."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from captions.caption_contract import CaptionContractError
from captions.caption_fingerprints import canonical_digest
from fingerprints import file_sha256

_FONT_SUFFIXES = {".otf", ".ttc", ".ttf"}
_LAST_RESORT_NAMES = {"lastresort.otf", "lastresort.ttf"}


@dataclass
class CaptionFontResolver:
    """One materialization-local fontconfig catalog and fallback cache."""

    tools: dict
    catalog: list[dict]
    system_cache: dict[tuple[str, int], tuple[str, list[dict]]]

    @classmethod
    def create(cls) -> "CaptionFontResolver":
        tools = {"fcMatch": _tool("fc-match"), "fcQuery": _tool("fc-query")}
        return cls(tools, _local_catalog(tools["fcQuery"]["path"]), {})

    def resolve(self, compilation: dict, styles: dict) -> dict:
        requests, files = _selected_files(compilation, styles, self)
        return _closure(requests, files, self.tools)


def _tool(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise CaptionContractError(
            f"caption font closure cannot resolve {name}")
    resolved = os.path.realpath(path)
    return {"path": resolved, "sha256": file_sha256(resolved)}


def _font_root() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "fonts"


def _ranges(value: str) -> tuple[tuple[int, int], ...]:
    result = []
    try:
        for token in value.split():
            bounds = token.split("-", 1)
            start = int(bounds[0], 16)
            end = int(bounds[-1], 16)
            result.append((start, end))
    except ValueError as exc:
        raise CaptionContractError(
            "fontconfig returned a malformed glyph charset") from exc
    return tuple(result)


def _query(path: str, tool: str) -> list[dict]:
    process = subprocess.run([
        tool, "--format", "%{family}\t%{style}\t%{charset}\n", path,
    ], capture_output=True, text=True)
    if process.returncode or not process.stdout.strip():
        raise CaptionContractError(
            f"caption font cannot be inspected: {path}")
    rows = []
    for line in process.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            raise CaptionContractError(
                f"caption font metadata is malformed: {path}")
        rows.append({
            "path": os.path.realpath(path),
            "families": tuple(
                name.strip() for name in fields[0].split(",")
                if name.strip()),
            "style": fields[1].strip(),
            "ranges": _ranges(fields[2]),
        })
    return rows


def _covers(record: dict, codepoint: int) -> bool:
    return any(start <= codepoint <= end
               for start, end in record["ranges"])


def _local_catalog(query_tool: str) -> list[dict]:
    root = _font_root()
    if not root.is_dir():
        raise CaptionContractError("caption local font directory is missing")
    paths = sorted(
        str(path) for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in _FONT_SUFFIXES)
    if not paths:
        raise CaptionContractError("caption local font closure is empty")
    return [row for path in paths for row in _query(path, query_tool)]


def _family_match(record: dict, family: str) -> bool:
    expected = family.casefold()
    return any(name.casefold() == expected for name in record["families"])


def _system_match(family: str, codepoint: int,
                  resolver: CaptionFontResolver) -> tuple[str, list[dict]]:
    key = (family, codepoint)
    if key in resolver.system_cache:
        return resolver.system_cache[key]
    tools = resolver.tools
    pattern = f"{family}:style=Bold:charset={codepoint:04x}"
    process = subprocess.run([
        tools["fcMatch"]["path"], "--format", "%{family}\t%{file}\n", pattern,
    ], capture_output=True, text=True)
    fields = process.stdout.splitlines()[0].split("\t", 1) \
        if not process.returncode and process.stdout.splitlines() else []
    if len(fields) != 2 or not os.path.isfile(fields[1]):
        raise CaptionContractError(
            f"caption glyph U+{codepoint:04X} has no local font")
    path = os.path.realpath(fields[1])
    families = {name.strip().casefold() for name in fields[0].split(",")}
    if os.path.basename(path).casefold() in _LAST_RESORT_NAMES \
            or ".lastresort" in families:
        raise CaptionContractError(
            f"caption glyph U+{codepoint:04X} resolved only to LastResort")
    records = _query(path, tools["fcQuery"]["path"])
    if not any(_covers(row, codepoint) for row in records):
        raise CaptionContractError(
            f"caption fallback font does not prove U+{codepoint:04X}")
    result = (path, records)
    resolver.system_cache[key] = result
    return result


def _cue_codepoints(cue: dict) -> tuple[str, set[int]]:
    style_id = cue.get("styleId")
    tokens = cue.get("tokens")
    if not isinstance(style_id, str) or not isinstance(tokens, list):
        raise CaptionContractError("caption font cue is malformed")
    result: set[int] = set()
    for token in tokens:
        text = token.get("text") if isinstance(token, dict) else None
        if not isinstance(text, str):
            raise CaptionContractError("caption font token is malformed")
        result.update(ord(char) for char in text if not char.isspace())
    return style_id, result


def _requested_codepoints(compilation: dict) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    cues = compilation.get("cues")
    if not isinstance(cues, list):
        raise CaptionContractError("caption font closure has no cue list")
    for cue in cues:
        style_id, codepoints = _cue_codepoints(cue)
        result.setdefault(style_id, set()).update(codepoints)
    return result


def _select_style_files(
    family: str, codepoints: set[int], resolver: CaptionFontResolver,
    selected: dict[str, list[dict]],
) -> None:
    local = [row for row in resolver.catalog if _family_match(row, family)]
    for row in local:
        if any(_covers(row, codepoint) for codepoint in codepoints):
            selected.setdefault(row["path"], []).append(row)
    for codepoint in sorted(codepoints):
        if any(_covers(row, codepoint) for row in local):
            continue
        path, records = _system_match(family, codepoint, resolver)
        selected.setdefault(path, []).extend(records)


def _selected_files(compilation: dict, styles: dict,
                    resolver: CaptionFontResolver) -> tuple[list[dict], list[dict]]:
    selected: dict[str, list[dict]] = {}
    requests = []
    for style_id, codepoints in sorted(
            _requested_codepoints(compilation).items()):
        style = styles.get(style_id)
        family = style.get("font") if isinstance(style, dict) else None
        if not isinstance(family, str) or not family:
            raise CaptionContractError(
                f"caption style {style_id!r} has no font family")
        _select_style_files(family, codepoints, resolver, selected)
        requests.append({
            "styleId": style_id, "family": family,
            "codepoints": [f"U+{value:04X}" for value in sorted(codepoints)],
        })
    files = [{
        "path": path, "sha256": file_sha256(path),
        "families": sorted({
            family for row in rows for family in row["families"]
        }),
    } for path, rows in sorted(selected.items())]
    return requests, files


def _closure(requests: list[dict], files: list[dict],
             tools: dict) -> dict:
    payload = {
        "schemaVersion": 1, "kind": "caption-font-closure",
        "tools": tools, "requests": requests, "files": files,
    }
    return {
        **payload, "authorityHash": canonical_digest(
            "sniper-caption-font-closure-v1", payload),
    }


def resolve_caption_font_closure(compilation: dict,
                                 styles: dict) -> dict:
    """Return content-addressed fontconfig and font-file render authority."""
    return CaptionFontResolver.create().resolve(compilation, styles)


def _merge_closure_value(
    value: dict, tools: dict, requests: dict, files: dict[str, dict],
) -> None:
    payload = {key: row for key, row in value.items()
               if key != "authorityHash"}
    if value.get("authorityHash") != canonical_digest(
            "sniper-caption-font-closure-v1", payload) \
            or value.get("tools") != tools:
        raise CaptionContractError("caption font closure is stale")
    for row in value["requests"]:
        key = (row["styleId"], row["family"])
        requests.setdefault(key, set()).update(row["codepoints"])
    for row in value["files"]:
        previous = files.get(row["path"])
        if previous is not None and previous != row:
            raise CaptionContractError("caption font file authority drifted")
        files[row["path"]] = row


def merge_caption_font_closures(values: list[dict]) -> dict:
    """Merge cue-local closures without widening any cue's cache key."""
    if not values:
        resolver = CaptionFontResolver.create()
        return _closure([], [], resolver.tools)
    tools = values[0]["tools"]
    requests: dict[tuple[str, str], set[str]] = {}
    files: dict[str, dict] = {}
    for value in values:
        _merge_closure_value(value, tools, requests, files)
    merged_requests = [{
        "styleId": key[0], "family": key[1],
        "codepoints": sorted(codepoints),
    } for key, codepoints in sorted(requests.items())]
    return _closure(
        merged_requests, [files[key] for key in sorted(files)], tools)
