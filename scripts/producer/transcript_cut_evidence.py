"""Transcript authority loading and hashing for transcript_cut_contract."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    duration: float
    transcript_path: str
    words: list[dict]


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _word_rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("words"), list):
        return payload["words"]
    rows = payload.get("transcript") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    if rows and all(isinstance(row, dict) and "start" in row and "end" in row
                    and "words" not in row and ("word" in row or "text" in row)
                    for row in rows):
        return rows
    return [word for row in rows if isinstance(row, dict)
            for word in (row.get("words") or []) if isinstance(word, dict)]


def _load_words(path: str, tag: str, errors: list[str]) -> list[dict]:
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{tag}: transcript unreadable: {exc}")
        return []
    words: list[dict] = []
    for index, raw in enumerate(_word_rows(payload)):
        try:
            text = str(raw.get("word", raw.get("text", ""))).strip()
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{tag}: transcript word[{index}] has invalid timing/text")
            continue
        if not text or end <= start:
            errors.append(f"{tag}: transcript word[{index}] is empty or end <= start")
            continue
        words.append({"word": text, "start": start, "end": end})
    words.sort(key=lambda word: (word["start"], word["end"]))
    if not words:
        errors.append(f"{tag}: transcript contains no timed words")
    return words


def _resolve_transcript(source: dict, manifest_path: str) -> str:
    relative = source.get("transcriptPath")
    if not isinstance(relative, str) or not relative:
        return ""
    if os.path.isabs(relative):
        return relative
    return os.path.join(os.path.dirname(os.path.abspath(manifest_path)), relative)


def source_evidence(manifest: dict, manifest_path: str, transcripts_dir: str,
                    required_ids: set[str], errors: list[str]
                    ) -> tuple[dict[str, SourceEvidence], list[dict]]:
    sources: dict[str, SourceEvidence] = {}
    authority: list[dict] = []
    for index, source in enumerate(manifest.get("sources") or []):
        source_id = str(source.get("id", ""))
        tag = f"manifest.sources[{index}]"
        path = _resolve_transcript(source, manifest_path)
        logical = os.path.relpath(path, transcripts_dir) if path else f"source-{index + 1}:missing-transcript"
        if logical.startswith(".."):
            logical = os.path.basename(path)
        authority.append({"path": logical.replace(os.sep, "/"),
                          "hash": file_hash(path) if path and os.path.isfile(path) else None})
        if source_id not in required_ids:
            continue
        if not source_id or not path or not os.path.isfile(path):
            errors.append(f"{tag}: id/transcriptPath must resolve to a readable transcript")
            continue
        if source_id in sources:
            errors.append(f"{tag}: duplicate source id {source_id!r}")
            continue
        try:
            duration = float(source["duration"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{tag}: duration must be numeric")
            continue
        sources[source_id] = SourceEvidence(
            source_id, duration, path, _load_words(path, tag, errors))
    return sources, authority
