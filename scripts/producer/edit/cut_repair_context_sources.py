"""Strict source/plan readers used by cut-repair context materialization."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from cross_runtime_canonical_json import (
    CrossRuntimeCanonicalJsonError,
    canonical_compact_json,
)

_HASH = re.compile(r"^[0-9a-f]{64}$")
_RATES = {
    23.976: (24000, 1001), 24.0: (24, 1), 25.0: (25, 1),
    29.97: (30000, 1001), 30.0: (30, 1), 50.0: (50, 1),
    59.94: (60000, 1001), 60.0: (60, 1),
}


class ContextMaterializationError(ValueError):
    """Live authority cannot yield safe cut-repair analysis inputs."""


def canonical_bytes(value: object) -> bytes:
    """Return the repository's deterministic JSON representation."""
    try:
        return canonical_compact_json(value).encode()
    except CrossRuntimeCanonicalJsonError as exc:
        raise ContextMaterializationError(
            "value is outside the cross-runtime JSON domain") from exc


def digest(value: object) -> str:
    """Hash a canonical JSON value."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _identity(row: os.stat_result) -> tuple[int, int, int, int, int]:
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


def _open_stable(path: str, label: str) -> tuple[int, os.stat_result]:
    if os.path.abspath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path):
        raise ContextMaterializationError(f"{label} path is not canonical")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode):
            raise ContextMaterializationError(
                f"{label} is not a regular file")
        if _identity(opened) != _identity(named):
            raise ContextMaterializationError(f"{label} changed while open")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _assert_stable(
        descriptor: int, opened: os.stat_result,
        path: str, label: str) -> None:
    after = os.fstat(descriptor)
    try:
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ContextMaterializationError(
            f"{label} changed while read") from exc
    if _identity(opened) != _identity(after) \
            or _identity(after) != _identity(named):
        raise ContextMaterializationError(f"{label} changed while read")


def _read_stable_bytes(path: str, label: str) -> bytes:
    descriptor, opened = _open_stable(path, label)
    chunks = []
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        _assert_stable(descriptor, opened, path, label)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def stable_file_digest(path: str, label: str) -> str:
    """Hash one canonical regular file while rejecting read races."""
    descriptor, opened = _open_stable(path, label)
    hasher = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            hasher.update(chunk)
        _assert_stable(descriptor, opened, path, label)
        return hasher.hexdigest()
    finally:
        os.close(descriptor)


def stable_json(path: str, label: str) -> tuple[dict, str]:
    """Read and hash one canonical JSON object from the same stable bytes."""
    payload = _read_stable_bytes(path, label)
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextMaterializationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContextMaterializationError(f"{label} is not an object")
    return value, hashlib.sha256(payload).hexdigest()


def stable_text(path: str, label: str, encoding: str = "utf-8") -> str:
    """Read one canonical regular text file without following a swap."""
    payload = _read_stable_bytes(path, label)
    try:
        return payload.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ContextMaterializationError(
            f"{label} is not valid {encoding}") from exc


def require_hash(value: object, label: str) -> str:
    """Return one validated lowercase SHA-256."""
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ContextMaterializationError(f"{label} is not a SHA-256")
    return value


def require_keys(value: dict, allowed: set[str], required: set[str],
                 label: str) -> None:
    """Enforce a closed JSON object."""
    if set(value) - allowed or required - set(value):
        raise ContextMaterializationError(
            f"{label} has unknown or missing fields")


def decimal_value(value: object, label: str) -> Decimal:
    """Parse finite, non-negative decimal timing."""
    if isinstance(value, bool) or not isinstance(
            value, (int, float, str, Decimal)):
        raise ContextMaterializationError(f"{label} is not decimal timing")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ContextMaterializationError(
            f"{label} is not decimal timing") from exc
    if not result.is_finite() or result < 0:
        raise ContextMaterializationError(f"{label} is negative/non-finite")
    return result


def to_sample(value: object, rate: int, label: str) -> int:
    """Quantize decimal seconds to the supplied source sample clock."""
    return int((decimal_value(value, label) * rate).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))


def rational_rate(value: object, label: str) -> tuple[int, int]:
    """Map a released decimal FPS spelling to its exact rational."""
    number = float(decimal_value(value, label))
    match = next((rate for key, rate in _RATES.items()
                  if abs(key - number) <= 0.001), None)
    if match is None:
        raise ContextMaterializationError(
            f"{label} is outside released rational FPS")
    return match


def source_rows(manifest: dict) -> dict[str, dict]:
    """Index unique manifest sources by controller-owned ID."""
    rows = manifest.get("sources")
    if not isinstance(rows, list):
        raise ContextMaterializationError("manifest has no sources")
    result = {}
    for index, value in enumerate(rows):
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) \
                or not value["id"] or value["id"] in result:
            raise ContextMaterializationError(
                f"manifest source {index} identity is invalid")
        result[value["id"]] = value
    return result


def target_source(plan: dict, directive: dict,
                  sources: dict[str, dict]) -> str:
    """Resolve a directive to one source actually retained in the cut."""
    target = directive.get("target")
    if not isinstance(target, dict):
        raise ContextMaterializationError("repair target is malformed")
    selected = target.get("sourceId")
    track = plan.get("cutTrack")
    if not isinstance(track, list) or not track:
        raise ContextMaterializationError("plan has no cutTrack")
    used = {row.get("sourceId") for row in track if isinstance(row, dict)}
    if selected is None:
        if len(used) != 1:
            raise ContextMaterializationError(
                "multi-source cut repair requires target.sourceId")
        selected = next(iter(used))
    if not isinstance(selected, str) or selected not in used \
            or selected not in sources:
        raise ContextMaterializationError(
            "target source is not a kept manifest source")
    return selected


def _word_row(word: object, utterance: dict, rate: int) -> dict:
    if not isinstance(word, dict) or not isinstance(word.get("word"), str):
        raise ContextMaterializationError("transcript word is malformed")
    start = to_sample(word.get("start"), rate, "word start")
    end = to_sample(word.get("end"), rate, "word end")
    if end <= start:
        raise ContextMaterializationError("transcript word range is empty")
    return {
        "word": word["word"], "startSample": start,
        "endSampleExclusive": end,
        **({"speaker": str(utterance["speaker"])}
           if utterance.get("speaker") is not None else {}),
    }


def transcript(source: dict, manifest_dir: str,
               source_id: str, sample_rate: int) -> dict:
    """Read admitted transcript timing and convert it to exact samples."""
    requested = source.get("transcriptPath")
    if not isinstance(requested, str) or not requested:
        raise ContextMaterializationError("target source has no transcript")
    lexical = os.path.abspath(os.path.join(manifest_dir, requested))
    root = os.path.realpath(manifest_dir)
    resolved = os.path.realpath(lexical)
    if os.path.commonpath([root, resolved]) != root or resolved == root:
        raise ContextMaterializationError("transcript escapes manifest directory")
    document, transcript_hash = stable_json(resolved, "target transcript")
    utterances = document.get("transcript")
    if not isinstance(utterances, list):
        raise ContextMaterializationError("target transcript has no utterances")
    words = []
    for utterance in utterances:
        if not isinstance(utterance, dict) \
                or not isinstance(utterance.get("words"), list):
            raise ContextMaterializationError("transcript utterance is malformed")
        words.extend(_word_row(word, utterance, sample_rate)
                     for word in utterance["words"])
    timing_hash = digest({
        "sourceId": source_id, "sampleRate": sample_rate,
        "transcriptSha256": transcript_hash, "words": words,
    })
    return {"sourceId": source_id, "timingHash": timing_hash, "words": words}


def source_media(source: dict, source_id: str) -> dict:
    """Reopen target media and prove it still matches admitted bytes."""
    media_path = source.get("path")
    expected = require_hash(source.get("contentHash"), "source content")
    if not isinstance(media_path, str):
        raise ContextMaterializationError("target source media path is absent")
    observed = stable_file_digest(media_path, "target source media")
    if observed != expected:
        raise ContextMaterializationError(
            "target source media does not match admitted snapshot authority")
    return {"sourceId": source_id, "path": media_path, "sha256": expected}
