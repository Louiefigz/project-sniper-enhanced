"""What a role packet assigns to read, and how large that assignment is.

Every frozen artifact gets a reading class from the maintained catalog (inspect, entries,
bound or history). Large request indexes are narrowed to the entries the subject actually
uses; code only locates those entries by their exact id, it never judges relevance. The size
record counts the packet's own bytes and the assigned text so qualification can separate
packet generation and reading from review work. Estimates are bytes / 4, not tokenizer counts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from role_packet_catalog import ARTIFACT_READING, ASSET_READING
from role_packet_files import MAX_RECEIPT_JSON, ArtifactError, json_bytes, read_json

BYTES_PER_TOKEN = 4
TEXT_SUFFIXES = {".json", ".md", ".html", ".htm", ".txt", ".ts", ".mts", ".js", ".mjs", ".css", ".svg", ".srt", ".vtt",
                 ".csv", ".py"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
METHOD = ("Estimated reading tokens = ceil(bytes / 4) over assigned UTF-8 text: the packet itself, assigned instruction "
          "lines, inspect-class text artifacts and located index entries. Images and media are counted, not tokenized; "
          "bound and history artifacts are reported separately and excluded from the total. Not a tokenizer count and "
          "not a measure of review time.")


def reading_class(row: dict) -> str:
    """Class for one artifact row by key prefix; asset rows by their role; unknown keys stay inspect."""
    key = row["key"]
    for prefix, kind in ARTIFACT_READING:
        if key.startswith(prefix):
            return kind
    role = key.split("-", 2)[2] if key.startswith("asset-") and key.count("-") >= 2 else None
    return ASSET_READING.get(role, "inspect")


def located_entries(path: str, collection: str, field: str, ids: list[str]) -> tuple[list[dict], list[str]] | None:
    """Exact-id entries of a JSON index collection with their pointers; None when the file has no such collection."""
    try:
        value = read_json(path, MAX_RECEIPT_JSON)
    except ArtifactError:
        return None
    items = value.get(collection)
    if not isinstance(items, list):
        return None
    rows = [{"id": item[field], "pointer": f"/{collection}/{index}",
             "bytes": len(json.dumps(item, ensure_ascii=False).encode())}
            for index, item in enumerate(items) if isinstance(item, dict) and item.get(field) in ids]
    return rows, sorted(set(ids) - {row["id"] for row in rows})


def entries_row(row: dict, focus: dict | None) -> dict:
    """Narrow an index to its used entries; a searched index stays assigned whole with its entries as starting points."""
    if focus is None:
        return {**row, "read": "inspect"}
    if not focus["ids"] and not focus["search"]:
        return {**row, "read": "bound"}
    found = located_entries(row["path"], focus["collection"], focus["field"], focus["ids"])
    if found is None:
        return {**row, "read": "inspect"}
    kind = "inspect" if focus["search"] else "entries"
    return {**row, "read": kind, "entries": found[0], "missingEntries": found[1]}


def with_reading(rows: list[dict], focus: dict | None) -> list[dict]:
    """Annotate every artifact with its reading class; `focus` is None for an authoring role (search it all)."""
    result = []
    for row in rows:
        kind = reading_class(row)
        if kind == "entries":
            result.append(entries_row(row, None if focus is None else focus.get(row["key"])))
            continue
        result.append({**row, "read": kind})
    return result


def medium(path: str) -> str:
    """text, image or media by file suffix."""
    suffix = Path(path).suffix.lower()
    return "text" if suffix in TEXT_SUFFIXES else "image" if suffix in IMAGE_SUFFIXES else "media"


def artifact_size(rows: list[dict], declared: list[dict]) -> dict:
    """Bytes and counts per reading class; located entries count only their own bytes."""
    size = {"files": len(rows), "inspectTextBytes": 0, "entryBytes": 0, "boundBytes": 0, "historyBytes": 0,
            "imagesToView": 0, "mediaToInspect": len(declared)}
    for row in rows:
        kind, form, count = row.get("read", "inspect"), medium(row["path"]), row.get("bytes", 0)
        if kind == "entries":
            size["entryBytes"] += sum(entry["bytes"] for entry in row["entries"])
        elif kind in ("bound", "history"):
            size[f"{kind}Bytes"] += count
        elif form == "text":
            size["inspectTextBytes"] += count
        else:
            size["imagesToView" if form == "image" else "mediaToInspect"] += 1
    return size


def instruction_size(rows: list[dict]) -> dict:
    """Assigned files, sections, lines and bytes, plus what the catalog deliberately excluded."""
    return {"files": sum(bool(row["sections"]) for row in rows), "sections": sum(len(row["sections"]) for row in rows),
            "lines": sum(row["assigned"]["lines"] for row in rows), "bytes": sum(row["assigned"]["bytes"] for row in rows),
            "excludedSections": sum(len(row["excluded"]) for row in rows),
            "excludedLines": sum(item["endLine"] - item["startLine"] + 1 for row in rows for item in row["excluded"])}


def tokens(count: int) -> int:
    """Rounded-up bytes / 4 estimate."""
    return math.ceil(count / BYTES_PER_TOKEN)


def size_record(packet: dict, packet_bytes: int) -> dict:
    """The size block for a given total packet length."""
    instructions = instruction_size(packet["instructions"])
    artifacts = artifact_size(packet["artifacts"], packet["declaredMedia"])
    estimate = {"packet": tokens(packet_bytes), "instructions": tokens(instructions["bytes"]),
                "artifacts": tokens(artifacts["inspectTextBytes"] + artifacts["entryBytes"])}
    estimate["total"] = sum(estimate.values())
    return {"method": METHOD, "packetBytes": packet_bytes, "instructions": instructions, "artifacts": artifacts,
            "estimatedReadingTokens": estimate}


def with_size(packet: dict) -> dict:
    """Record the packet's own size, including the size block, as a fixed point of its serialization."""
    guess = len(json_bytes({**packet, "size": size_record(packet, 0)}))
    for _attempt in range(8):
        sized = {**packet, "size": size_record(packet, guess)}
        actual = len(json_bytes(sized))
        if actual == guess:
            return sized
        guess = actual
    raise ArtifactError("packet size did not converge; refusing to publish an unmeasured packet")
