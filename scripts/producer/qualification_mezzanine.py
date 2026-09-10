"""Governed over-cap conversion that never bypasses normal media admission."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from headless.qualification_mezzanine_policy import (
    DEFAULT_TIMEOUT_SECONDS,
    PROJECT_FPS,
)
from headless.qualification_mezzanine_runtime import run_isolated_transcode
from ingest_admission_contract import canonical_bytes
from qualification_mezzanine_contract import (
    EvidenceInput,
    build_evidence,
    validate_worker,
    verify_evidence_document,
)
from qualification_mezzanine_files import (
    FileFact,
    observe_overcap_source,
    observe_qualified_output,
    read_canonical_evidence,
    regular_directory,
)
from qualification_mezzanine_publish import (
    PublishFile,
    assert_attempt_path,
    cleanup_attempt,
    close_attempt,
    new_attempt,
    publication_transaction,
    seal_stage_media,
    write_stage,
)


@dataclass(frozen=True)
class QualificationRequest:
    """One explicit immutable-output qualification request."""

    source: str
    output: str
    evidence: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    target_fps: int = 24


@dataclass(frozen=True)
class QualificationRunners:
    """Injectable boundaries for deterministic failure tests."""

    source_observer: Callable[[str], FileFact]
    isolated_transcode: Callable[[str, str, int, int], dict]


def _validate_request(request: QualificationRequest) -> None:
    paths = [request.source, request.output, request.evidence]
    if any(type(value) is not str or not os.path.isabs(value) for value in paths):
        raise RuntimeError("qualification paths must be absolute")
    if len(set(paths)) != len(paths):
        raise RuntimeError("qualification paths must be distinct")
    source = os.lstat(request.source)
    if (not stat.S_ISREG(source.st_mode) or stat.S_ISLNK(source.st_mode)
            or source.st_nlink != 1):
        raise RuntimeError("qualification source must be one regular non-link file")
    output, evidence = Path(request.output), Path(request.evidence)
    if output.suffix.lower() != ".mp4" or evidence.suffix.lower() != ".json":
        raise RuntimeError("qualification output must be MP4 with JSON evidence")
    if output.parent != evidence.parent:
        raise RuntimeError("qualification output and evidence must share a directory")
    regular_directory(output.parent, "qualification output directory")
    if os.path.lexists(output) or os.path.lexists(evidence):
        raise RuntimeError("qualification output or evidence already exists")
    valid_timing = (
        type(request.timeout_seconds) is int
        and 300 <= request.timeout_seconds <= 24 * 60 * 60
        and type(request.target_fps) is int
        and request.target_fps in PROJECT_FPS
    )
    if not valid_timing:
        raise RuntimeError("qualification timing policy is invalid")


def default_runners() -> QualificationRunners:
    """Production boundaries; tests inject inert deterministic substitutes."""
    return QualificationRunners(
        observe_overcap_source, run_isolated_transcode)


def _build_document(
    request: QualificationRequest,
    source: FileFact,
    output: FileFact,
    envelope: dict,
) -> dict:
    worker = validate_worker(
        envelope, request.target_fps, source, output)
    authority = EvidenceInput(
        source, output, request.output, request.target_fps,
        {**envelope, "worker": worker})
    return build_evidence(authority)


def build_qualification_mezzanine(
    request: QualificationRequest,
    runners: QualificationRunners | None = None,
) -> dict:
    """Build and evidence-first publish; eligibility stays false until admission."""
    _validate_request(request)
    selected = runners or default_runners()
    source_before = selected.source_observer(request.source)
    attempt = new_attempt(Path(request.output).parent)
    try:
        assert_attempt_path(attempt)
        envelope = selected.isolated_transcode(
            request.source, str(attempt.path), request.timeout_seconds,
            request.target_fps)
        assert_attempt_path(attempt)
        stage_media = attempt.path / "qualified.mp4"
        output = observe_qualified_output(str(stage_media))
        source_after = selected.source_observer(request.source)
        if source_after != source_before:
            raise RuntimeError("over-cap source changed during qualification")
        output = seal_stage_media(attempt, "qualified.mp4", output)
        document = _build_document(request, source_before, output, envelope)
        evidence = write_stage(
            attempt, "qualification.json", canonical_bytes(document))
        files = (
            PublishFile(
                "qualification.json", Path(request.evidence).name, evidence),
            PublishFile("qualified.mp4", Path(request.output).name, output),
        )
        with publication_transaction(attempt, files):
            cleanup_attempt(attempt)
            return verify_qualification_evidence(request.evidence)
    finally:
        try:
            cleanup_attempt(attempt, strict=False)
        finally:
            close_attempt(attempt)


def verify_qualification_evidence(path: str) -> dict:
    """Verify canonical evidence and exact output without admitting it."""
    return verify_evidence_document(read_canonical_evidence(path))
