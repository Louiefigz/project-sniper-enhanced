"""Compare an actual delivery decode with its intended, fully mastered program."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from scipy.io import wavfile

from audio.pcm_local_comparison import PCMComparisonConfig, compare_pcm
from audio.program_master_bus import ProgramMaster
from audio.render_audio_authority import run_audio
from cut_preview_io import MAX_JSON, MAX_MEDIA, file_hash

MAXIMUM_DECODER_PADDING = 1023
WAV_HEADER_ALLOWANCE = 65536


class ProgramDeliverySignalError(RuntimeError):
    """Carry failed comparison evidence to the existing unpublished receipt."""

    def __init__(self, message: str, evidence: dict) -> None:
        """Preserve measurements and decoder failures without approving output."""
        super().__init__(message)
        self.evidence = evidence


def _decode(candidate: str, directory: Path, context: tuple[str, int]) -> Path:
    """Decode without clock repair; reaching the disk bound is a failure."""
    ffmpeg, maximum = context
    path = directory / "decoded.wav"
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
        "-n", "-i", candidate, "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le",
        "-fs", str(maximum), str(path)])
    if path.stat().st_size >= maximum:
        raise RuntimeError("delivery PCM decode reached its disk bound")
    return path


def _compare(reference: Path, decoded: Path, config: PCMComparisonConfig) -> dict:
    """Use memory maps and retain every local window, including quiet evidence."""
    expected_rate, expected = wavfile.read(reference, mmap=True)
    actual_rate, actual = wavfile.read(decoded, mmap=True)
    if expected_rate != config.sample_rate or actual_rate != config.sample_rate:
        raise ValueError("delivery/reference PCM sample rate differs from the program clock")
    return compare_pcm(expected, actual, config)


def _error_detail(error: BaseException) -> dict:
    """Keep bounded subprocess diagnostics in a JSON-safe failure record."""
    stderr = getattr(error, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return {"errorType": type(error).__name__, "error": str(error),
            "stderr": str(stderr)[-1200:] if stderr is not None else None}


def _bound_record(evidence: dict) -> None:
    """Refuse oversized proof and retain a bounded, explicit failure summary."""
    evidence["windowCount"] = len(evidence.get("windows", []))
    if len(json.dumps(evidence, allow_nan=False).encode()) <= MAX_JSON // 2:
        return
    evidence.pop("windows", None)
    evidence["windowDetailsOmitted"] = "record-budget-exceeded; candidate is unqualified"
    raise ValueError("delivery local signal receipt exceeds its bounded record budget")


def verify_program_delivery_signal(master: ProgramMaster, candidate: str,
                                   maximum_media_bytes: int = MAX_MEDIA) -> dict:
    """Fail before publication on changed bytes, bad decoding or local signal loss.

    The caller retains the separate AAC packet/clock gate. Quiet-only references
    can pass quiet error checks, with activeEvidenceAvailable explicitly false.
    """
    started = time.monotonic()
    evidence = {"status": "incomplete", "passed": False, "humanListeningApproved": False}
    try:
        config = PCMComparisonConfig(master.source_bus.samples, 48000, MAXIMUM_DECODER_PADDING)
        maximum_decode = (config.expected_samples + config.maximum_decoder_padding) * 8 + WAV_HEADER_ALLOWANCE
        if type(maximum_media_bytes) is not int or maximum_media_bytes <= 0 or maximum_decode > maximum_media_bytes:
            raise ValueError("delivery PCM decode exceeds the explicit media byte budget")
        reference, encoded = Path(master.path).absolute(), Path(candidate).absolute()
        before = {"referenceSha256": file_hash(reference, maximum_media_bytes),
                  "candidateSha256": file_hash(encoded, maximum_media_bytes)}
        evidence.update(before, maximumDecodeBytes=maximum_decode)
        with tempfile.TemporaryDirectory(prefix=".program-signal-", dir=encoded.parent) as scratch:
            decoded = _decode(candidate, Path(scratch),
                              (master.source_bus.admission.tools["ffmpeg"]["path"], maximum_decode))
            evidence.update(_compare(reference, decoded, config))
        stable = (file_hash(reference, maximum_media_bytes) == before["referenceSha256"]
                  and file_hash(encoded, maximum_media_bytes) == before["candidateSha256"])
        evidence.update(inputsStable=stable, elapsedSeconds=time.monotonic() - started)
        _bound_record(evidence)
        if not stable or not evidence["passed"]:
            raise RuntimeError("delivery local signal failed or compared bytes changed")
        return evidence
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        evidence.update(_error_detail(error), status="local-signal-checks-failed", passed=False,
                        elapsedSeconds=time.monotonic() - started)
        raise ProgramDeliverySignalError("full-program delivery local signal unqualified", evidence) from error
