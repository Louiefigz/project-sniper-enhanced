"""Prepared picture-candidate fixture with two transcript-bound takes."""
from __future__ import annotations

import hashlib
import os

from edit.alternate_take_candidates import (
    CandidateSetInput,
    build_alternate_take_candidate_set,
)
from edit.cut_repair_context_sources import canonical_bytes, digest
from edit.target_resolver import build_word_refs
from tests._p2_candidate_qc_fixture import (
    CandidateQcFixture,
    _PackageAuthority,
    _store,
    _write,
)


def _utterance(start: float) -> dict:
    words = ("restore", "this", "phrase")
    rows = []
    for index, word in enumerate(words):
        word_start = start + index * 0.2
        rows.append({
            "word": word,
            "start": word_start,
            "end": word_start + 0.2,
        })
    return {
        "start": start, "end": start + 0.6,
        "text": "restore this phrase.", "words": rows,
    }


class AlternateTakeFixture:
    """Reuse real media while replacing preparation with a picture repair."""

    def __init__(self) -> None:
        self.base = CandidateQcFixture()
        self.producer = self.base.producer
        self.transcript_path = os.path.join(
            self.producer, "raw.transcript.json")
        transcript = {
            "transcript": [_utterance(0.4), _utterance(2.0)]}
        transcript_bytes = canonical_bytes(transcript)
        _write(self.transcript_path, transcript_bytes)
        self.transcript_hash = hashlib.sha256(transcript_bytes).hexdigest()
        self.context = self._context()
        self.operation = self._operation()
        self.preparation_hash = self._preparation()
        self.candidate_set = build_alternate_take_candidate_set(
            CandidateSetInput(
                self.context, self.operation, self.transcript_path, 0))
        self.selected = next(
            row for row in self.candidate_set["candidates"]
            if row["role"] == "later")

    def _timed_rows(self) -> list[dict]:
        rate = self.base.source_rate
        return [
            {
                "word": word,
                "startSample": round((start + index * 0.2) * rate),
                "endSampleExclusive":
                    round((start + (index + 1) * 0.2) * rate),
            }
            for start in (0.4, 2.0)
            for index, word in enumerate(("restore", "this", "phrase"))
        ]

    def _context(self) -> dict:
        rows = self._timed_rows()
        rate = self.base.source_rate
        timing_hash = digest({
            "sourceId": "raw-1", "sampleRate": rate,
            "transcriptSha256": self.transcript_hash, "words": rows,
        })
        core = {
            "schemaVersion": 1,
            "kind": "cut-repair-analysis-context",
            "transcript": {
                "sourceId": "raw-1", "timingHash": timing_hash,
                "words": rows,
            },
            "segments": [{
                "segmentId": "segment-a", "elementVersion": 1,
                "sourceId": "raw-1", "sourceRate": rate,
                "sourceSamples": {
                    "startSample": 0, "endSampleExclusive": 144_000},
                "outputFrames": {
                    "startFrame": 0, "endFrameExclusive": 90},
                "speed": {"numerator": "1", "denominator": "1"},
                "sourceFps": {"numerator": "30", "denominator": "1"},
            }],
            "clock": {
                "fps": {"numerator": "30", "denominator": "1"},
                "sampleRate": 48_000,
            },
            "totalFrames": 120,
            "sourceMedia": {
                "sourceId": "raw-1", "path": self.base.source_path,
                "sha256": self.base.source_hash,
            },
        }
        return {**core, "authorityHash": digest(core)}

    def _operation(self) -> dict:
        transcript = self.context["transcript"]
        refs = build_word_refs(
            "raw-1", transcript["words"], transcript["timingHash"])
        later = refs[3:6]
        source_range = {
            "startSample": later[0].samples.start_sample,
            "endSampleExclusive": later[-1].samples.end_sample_exclusive,
        }
        return {
            "schemaVersion": 1, "operation": "cut.restoreSpeech",
            "method": "extend-and-reclaim-silence",
            "segment": {
                "segmentId": "segment-a", "elementVersion": 1, "edge": "end"},
            "extensionFrames": 18,
            "sourceSampleRate": self.base.source_rate,
            "sourceExtension": source_range,
            "sourceVideoFrameRange": {
                "startFrame": 60, "endFrameExclusive": 78},
            "sourceFrameRate": {"numerator": "30", "denominator": "1"},
            "target": {
                "kind": "word-range", "sourceId": "raw-1",
                "wordIds": [word.word_id for word in later],
                "occurrence": 2, "sourceSampleRange": source_range,
                "transcriptTimingHash": transcript["timingHash"],
            },
            "audioDirtyWindows": [{
                "startFrame": 0, "endFrameExclusive": 90}],
            "pictureDirtyWindows": [{
                "startFrame": 0, "endFrameExclusive": 90}],
        }

    def _preparation(self) -> str:
        context_hash, _ = _store(self.base.authority, self.context)
        operation_hash = digest(self.operation)
        descriptor = self.base._descriptor(operation_hash)
        descriptor_hash, _ = _store(self.base.authority, descriptor)
        descriptor_path = os.path.join(
            self.base.staging, "cut-repair-rendered-candidate.json")
        _write(descriptor_path, canonical_bytes(descriptor))
        package = self.base._package(_PackageAuthority(
            self.context, context_hash, self.operation, operation_hash,
            descriptor_hash, descriptor_path))
        package_hash, _ = _store(self.base.authority, package)
        return package_hash

    def clean(self) -> None:
        """Remove the delegated real-media fixture."""
        self.base.clean()
