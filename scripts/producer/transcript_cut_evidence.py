"""Transcript authority loading and hashing for transcript_cut_contract."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import read_bytes
from transcript_source_authority import verify_result


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    duration: float
    transcript_path: str
    words: list[dict]
    #: Silence measured in the source audio, when it could be read. A word's timing is
    #: whisper's guess; this is the audio itself, and the cut gate weighs both.
    silence: tuple[tuple[float, float], ...] = ()
    #: The dBFS gate that measurement used (None when nothing was measured).
    silence_gate_dbfs: float | None = None

    def measured_silent(self, start: float, end: float, margin: float = 0.0) -> bool:
        """True when [start, end] lies inside one measured silence, with ``margin`` spare."""
        return any(span_start <= start - margin and end + margin <= span_end
                   for span_start, span_end in self.silence)


def _measure_source_silence(source: dict, manifest_path: str
                            ) -> tuple[tuple[tuple[float, float], ...], float | None]:
    """Silence measured in this source's own audio, or nothing when it cannot be read.

    The gate's other evidence is the transcript, whose word bounds whisper pads (and
    starts late). Where the two disagree the audio decides, so it is read here when it
    is reachable; when it is not, the gate behaves exactly as it did before.
    """
    media = source.get("path")
    if not isinstance(media, str) or not media:
        return (), None
    if not os.path.isabs(media):
        media = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), media)
    if not os.path.isfile(media):
        return (), None
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # scripts/
    try:
        from local_whisper_speech_edges import SpeechEdgeError, frame_levels, measure_silences
        _levels, gate = frame_levels(media)
        return tuple(measure_silences(media)), round(gate, 2)
    except (ImportError, SpeechEdgeError, OSError, ValueError):
        return (), None


@dataclass(frozen=True)
class CutParent:
    """Initial small document bytes, not a later hash of possibly changed input."""

    path: str
    raw: bytes
    value: dict

    @property
    def sha256(self) -> str:
        """Hash only the exact initial bytes that were parsed and validated."""
        return hashlib.sha256(self.raw).hexdigest()


def _parent_bytes(path: str) -> bytes:
    """Keep legacy directory aliases readable, but never follow a file link."""
    absolute = Path(os.path.abspath(path))
    return read_bytes(absolute.parent.resolve(strict=True) / absolute.name)


def load_cut_parent(path: str) -> CutParent:
    """Capture one bounded initial JSON object for the entire cut check."""
    raw = _parent_bytes(path)
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("cut parent must be a JSON object")
    return CutParent(path, raw, value)


def recheck_cut_parents(parents: tuple[CutParent, ...], errors: list[str]) -> None:
    """Fail if receipt publication no longer refers to the initial parent bytes."""
    for parent in parents:
        try:
            if _parent_bytes(parent.path) != parent.raw:
                raise RuntimeError(f"{parent.path}: parent bytes changed during cut validation")
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"cut parent publication blocked: {exc}")


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    raw = canonical_compact_json(value)
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


def _load_payload(path: str, tag: str, errors: list[str]) -> Any:
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{tag}: transcript unreadable: {exc}")
        return None


def _confidence_fields(raw: dict, tag: str, errors: list[str]) -> dict | None:
    """Keep optional, uncalibrated confidence; reject invalid supplied metadata."""
    if "confidence" not in raw:
        return {}
    confidence = raw["confidence"]
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1 \
            or not math.isfinite(confidence):
        errors.append(f"{tag} has invalid confidence")
        return None
    return {"confidence": confidence}


def _load_words(payload: Any, tag: str, errors: list[str]) -> list[dict]:
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
        confidence = _confidence_fields(raw, f"{tag}: transcript word[{index}]", errors)
        if confidence is None:
            continue
        words.append({"word": text, "start": start, "end": end, **confidence})
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


def _correction_problem(payload: object, source: dict, path: str,
                        context: tuple[str | None, str]) -> str | None:
    """Keep correction-store imports lazy to avoid the legacy review import cycle."""
    expected, manifest_path = context
    marked = type(payload) is dict and bool({"timingCorrectionAuthority", "sourceWordCorrectionAuthority"}.intersection(payload))
    if not marked and ".sniper-timing-corrections" not in Path(path).parts \
            and not Path(manifest_path).name.startswith("asset_manifest.timing-"):
        return None
    from transcript_correction_read import correction_error
    try:
        if hashlib.sha256(_parent_bytes(path)).hexdigest() != expected:
            return "timing correction transcript changed after initial cut evidence observation"
        problem = correction_error(payload, source, path, manifest_path)
        if hashlib.sha256(_parent_bytes(path)).hexdigest() != expected:
            return "timing correction transcript changed during cut evidence observation"
        return problem
    except (OSError, RuntimeError, ValueError) as exc:
        return f"timing correction transcript observation blocked: {exc}"


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
        payload = _load_payload(path, tag, errors)
        if source.get("sourceSha256") is not None:
            problem = verify_result(payload, source, path)
            if problem:
                errors.append(f"{tag}: {problem}")
        correction_problem = _correction_problem(payload, source, path, (authority[-1]["hash"], manifest_path))
        if correction_problem:
            errors.append(f"{tag}: {correction_problem}")
        silence, gate = _measure_source_silence(source, manifest_path)
        sources[source_id] = SourceEvidence(
            source_id, duration, path, _load_words(payload, tag, errors), silence, gate)
    return sources, authority
