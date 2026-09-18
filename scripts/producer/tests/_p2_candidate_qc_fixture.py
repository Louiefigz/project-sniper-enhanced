"""Real-media authority fixture for candidate-bound cut-repair QC tests."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass

from edit.cut_repair_candidate_qc_pin import PinRequest, pin_tool_manifest
from edit.cut_repair_candidate_qc_tools import (
    approved_alignment_paths,
    approved_visual_oracle_paths,
)
from edit.cut_repair_context_sources import canonical_bytes, digest
from edit.target_resolver import build_word_refs
from tests._p2_candidate_qc_options import CandidateQcOptions


@dataclass(frozen=True)
class _PackageAuthority:
    context: dict
    context_hash: str
    operation: dict
    operation_hash: str
    descriptor_hash: str
    descriptor_path: str


def _write(path: str, payload: bytes, executable: bool = False) -> None:
    with open(path, "wb") as stream:
        stream.write(payload)
    if executable:
        os.chmod(path, 0o700)


def _store(directory: str, value: dict) -> tuple[str, str]:
    payload = canonical_bytes(value)
    value_hash = hashlib.sha256(payload).hexdigest()
    path = os.path.join(directory, f"{value_hash}.json")
    _write(path, payload)
    return value_hash, path


def _source(path: str, sample_rate: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise unittest.SkipTest("ffmpeg is unavailable")
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        "aevalsrc=0.18*sin(2*PI*(170+45*t)*t)+"
        f"0.08*sin(2*PI*(311+27*t)*t):s={sample_rate}:d=4",
        "-ac", "1", "-c:a", "pcm_s16le", "-bitexact", "-y", path,
    ]
    subprocess.run(command, check=True, capture_output=True)


def _candidate(path: str, source_path: str, duplicate: bool) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise unittest.SkipTest("ffmpeg is unavailable")
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", source_path, "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=30:d=4",
    ]
    if duplicate:
        graph = (
            "[0:a]atrim=start=0:end=2,asetpts=PTS-STARTPTS[a0];"
            "[0:a]atrim=start=1:end=1.5,asetpts=PTS-STARTPTS[a1];"
            "[0:a]atrim=start=2:end=3.5,asetpts=PTS-STARTPTS[a2];"
            "[a0][a1][a2]concat=n=3:v=0:a=1[a]"
        )
        command.extend(["-filter_complex", graph, "-map", "1:v:0", "-map", "[a]"])
    else:
        command.extend(["-map", "1:v:0", "-map", "0:a:0"])
    command.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", "-y", path,
    ])
    subprocess.run(command, check=True, capture_output=True)


def _whisper_script(path: str, text: str) -> None:
    source = f"""#!/usr/bin/env python3
import json
import sys
output = sys.argv[sys.argv.index("-of") + 1] + ".json"
with open(output, "w", encoding="utf-8") as stream:
    json.dump({{"transcription": [{{"text": {text!r}}}]}}, stream)
"""
    _write(path, source.encode(), True)


class CandidateQcFixture:
    """One full-plan candidate with content-addressed preparation objects."""

    def __init__(
        self,
        options: CandidateQcOptions | None = None,
    ) -> None:
        config = options or CandidateQcOptions()
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.producer = os.path.join(self.root, "producer")
        self.authority = os.path.join(
            self.producer, ".sniper-authority-v1", "objects", "cut-repairs")
        self.staging = os.path.join(
            self.producer, ".sniper-cut-repair-staging", "attempt")
        os.makedirs(self.authority)
        os.makedirs(self.staging)
        self.source_rate = config.source_rate
        self.target_start_sample = (
            config.source_rate if config.target_start_sample is None
            else config.target_start_sample)
        self.dirty_start_frame = config.dirty_start_frame
        self.source_path = os.path.join(self.producer, "admitted-source.wav")
        _source(self.source_path, config.source_rate)
        self.source_hash = self._file_hash(self.source_path)
        self.candidate_path = os.path.join(self.staging, "candidate.mp4")
        _candidate(
            self.candidate_path, self.source_path, config.duplicate_alignment)
        self.candidate_hash = self._file_hash(self.candidate_path)
        self.tools_dir = os.path.join(self.producer, "qc-tools")
        os.makedirs(self.tools_dir)
        self.whisper_path = os.path.join(self.tools_dir, "whisper")
        self.whisper_model = os.path.join(self.tools_dir, "whisper-model.bin")
        _whisper_script(self.whisper_path, config.whisper_text)
        _write(self.whisper_model, b"test whisper model")
        (
            self.aligner_runtime,
            self.aligner_implementation,
            self.aligner_policy,
        ) = approved_alignment_paths()
        (
            self.visual_runtime,
            self.visual_implementation,
            self.visual_policy,
        ) = approved_visual_oracle_paths()
        self.assert_runtime_matches_fixture()
        self.preparation_hash = self._authority_objects()
        self.tool_manifest_path = os.path.join(
            self.producer, "cut_repair_qc_tools_v1.json")
        self._pin_tools(config.aligner)

    @staticmethod
    def _file_hash(path: str) -> str:
        with open(path, "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()

    def _context(self) -> tuple[dict, tuple[str, ...]]:
        timing_hash = "1" * 64
        start = self.target_start_sample
        span = self.source_rate // 2
        first_end = start + span // 3
        second_end = start + 2 * span // 3
        end = start + span
        rows = [
            {"word": "restore", "startSample": start,
             "endSampleExclusive": first_end},
            {"word": "this", "startSample": first_end,
             "endSampleExclusive": second_end},
            {"word": "phrase", "startSample": second_end,
             "endSampleExclusive": end},
        ]
        refs = build_word_refs("raw-1", rows, timing_hash)
        core = {
            "schemaVersion": 1,
            "kind": "cut-repair-analysis-context",
            "transcript": {
                "sourceId": "raw-1", "timingHash": timing_hash,
                "words": rows,
            },
            "clock": {
                "fps": {"numerator": "30", "denominator": "1"},
                "sampleRate": 48000,
            },
            "totalFrames": 120,
            "sourceMedia": {
                "sourceId": "raw-1", "path": self.source_path,
                "sha256": self.source_hash,
            },
        }
        return {**core, "authorityHash": digest(core)}, tuple(
            row.word_id for row in refs)

    def _operation(self, words: tuple[str, ...]) -> dict:
        start = self.target_start_sample
        return {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "sourceSampleRate": self.source_rate,
            "target": {
                "kind": "word-range", "sourceId": "raw-1",
                "wordIds": list(words), "occurrence": 1,
                "sourceSampleRange": {
                    "startSample": start,
                    "endSampleExclusive": start + self.source_rate // 2},
                "transcriptTimingHash": "1" * 64,
            },
            "audioDirtyWindows": [{
                "startFrame": self.dirty_start_frame,
                "endFrameExclusive": self.dirty_start_frame + 30}],
            "pictureDirtyWindows": [],
        }

    def _authority_objects(self) -> str:
        context, words = self._context()
        context_hash, _ = _store(self.authority, context)
        operation = self._operation(words)
        operation_hash = digest(operation)
        descriptor = self._descriptor(operation_hash)
        descriptor_hash, _ = _store(self.authority, descriptor)
        descriptor_path = os.path.join(
            self.staging, "cut-repair-rendered-candidate.json")
        _write(descriptor_path, canonical_bytes(descriptor))
        package = self._package(_PackageAuthority(
            context, context_hash, operation, operation_hash,
            descriptor_hash, descriptor_path))
        package_hash, _ = _store(self.authority, package)
        return package_hash

    def _descriptor(self, operation_hash: str) -> dict:
        return {
            "schemaVersion": 1,
            "kind": "cut-repair-rendered-plan-candidate",
            "status": "candidate-proved",
            "operationHash": operation_hash,
            "reviewPlanObjectHash": "2" * 64,
            "reviewPlanContentHash": "3" * 64,
            "reviewTimelineMapHash": "4" * 64,
            "reviewRenderGraphHash": "5" * 64,
            "reviewRenderGraphReceiptHash": "6" * 64,
            "reviewRenderGraphCandidatePointerHash": "7" * 64,
            "candidatePath": self.candidate_path,
            "candidateSha256": self.candidate_hash,
        }

    def _package(self, value: _PackageAuthority) -> dict:
        action = {
            "operation": value.operation,
            "operationHash": value.operation_hash,
            "reviewPlanObjectHash": "2" * 64,
            "reviewPlanContentHash": "3" * 64,
            "reviewTimelineMapHash": "4" * 64,
            "reviewRenderGraphHash": "5" * 64,
        }
        return {
            "schemaVersion": 1, "kind": "cut-repair-preparation-package",
            "status": "rendered-plan-candidate-prepared",
            "idempotencyKey": "10000000-0000-4000-8000-000000000001",
            "targetDirectiveHash": "8" * 64,
            "contextAuthorityHash": value.context["authorityHash"],
            "contextObjectHash": value.context_hash,
            "analysisObjectHash": "9" * 64,
            "parentRevisionHash": "a" * 64, "proposedReviewAction": action,
            "reviewProjectionHash": "b" * 64,
            "renderInvalidationStrategy": "dialogue-stem",
            "fragmentReceipt": {}, "compositeReceipt": {},
            "fragmentMediaSha256": "c" * 64,
            "compositeMediaSha256": "d" * 64,
            "reviewRenderGraphReceiptHash": "6" * 64,
            "reviewRenderGraphCandidatePointerHash": "7" * 64,
            "reviewCandidateMediaSha256": self.candidate_hash,
            "reviewCandidatePath": self.candidate_path,
            "reviewCandidateDescriptorHash": value.descriptor_hash,
            "reviewCandidateDescriptorPath": value.descriptor_path,
            "previousRenderGraphHash": None,
            "previousRenderGraphReceiptHash": None,
            "blockingRequirements": [
                "alignment-qc", "vad-qc", "retranscription-qc", "seam-qc",
                "cut-review-staging", "operator-audition",
                "promotion-package-sealing", "final-media-activation"],
            "preparedAt": "2026-07-29T12:00:00.000Z",
        }

    def _pin_tools(self, aligner: bool) -> None:
        ffmpeg = os.path.realpath(shutil.which("ffmpeg") or "")
        request = PinRequest(
            ffmpeg, self.whisper_path, self.whisper_model,
            self.aligner_runtime if aligner else None,
            self.aligner_implementation if aligner else None,
            self.aligner_policy if aligner else None,
            self.visual_runtime, self.visual_implementation,
            self.visual_policy)
        pin_tool_manifest(self.tool_manifest_path, request)

    def assert_runtime_matches_fixture(self) -> None:
        """Catch a test runner that cannot execute the approved adapter."""
        if os.path.realpath(sys.executable) != self.aligner_runtime:
            raise RuntimeError("candidate-QC fixture uses the wrong Python runtime")

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
