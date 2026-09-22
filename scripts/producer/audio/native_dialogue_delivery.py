"""Finish a native picture with intended float dialogue using shared delivery logic."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path

from audio.audio_mix_delivery import _observe_final_audio, measure_delivery
from audio.aac_peak_candidates import AAC_PEAK_CANDIDATE_POLICY, corrected_peak_profile
from audio.audio_mix_picture import observe_picture_source, packet_signature, verify_picture_copy
from audio.float_master import FloatMasterInput, render_float_master
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE, MasteringProfile
from audio.native_aac_encoding import native_aac_arguments, native_aac_encoding_policy
from audio.native_audio_donor import admit_audio_donor, verify_audio_donor, verify_prepared_donor
from audio.program_audio_clock import exact_aac_audio_clock, exact_float_audio_clock
from audio.program_delivery_signal import (FloatDeliveryReference, ProgramDeliverySignalError,
                                           verify_float_delivery_signal)
from audio.render_audio_authority import run_audio
from fingerprints import file_sha256
from producer_config import ENCODE, MASTERING_POLICY_VERSION
from audit.audio_quality import check_audio_quality
from audit.audit_checks import FAIL, WARN

LOGGER = logging.getLogger(__name__)


class NativeAacDeliveryError(RuntimeError):
    """Actual encoded delivery failed after picture, clock and local signal checks passed."""


@dataclass(frozen=True)
class NativeDialogueDelivery:
    """Caller-bound picture and intended dialogue; caller owns source/cut provenance."""

    picture: Path
    premaster: Path
    samples: int
    directory: Path
    picture_sha256: str
    premaster_sha256: str
    prior_receipt: Path | None = None
    profile: MasteringProfile = NATIVE_SHORT_MASTERING_PROFILE
    review_sections: tuple[dict, ...] = ()
    prepared_master: tuple[Path, str] | None = None
    prepared_donor: tuple[Path, str] | None = None


def _stable(request: NativeDialogueDelivery) -> None:
    """Reject changed audio or picture before and after measurement/encoding."""
    if file_sha256(str(request.picture)) != request.picture_sha256 \
            or file_sha256(str(request.premaster)) != request.premaster_sha256:
        raise RuntimeError("Native dialogue delivery input bytes changed")


def _master(request: NativeDialogueDelivery, receipt: dict, tools: tuple[str, str]) -> Path:
    """Use the same mastering intelligence as the ordinary full-program path."""
    if request.prepared_master is not None:
        from audio.native_master_preparation import reuse_prepared_master
        return reuse_prepared_master(request, receipt, tools)
    ffmpeg, ffprobe = tools
    receipt["premasterClock"] = exact_float_audio_clock(str(request.premaster), ffprobe, request.samples)
    measured, code, error = _observe_final_audio(str(request.premaster))
    if code or measured is None:
        raise RuntimeError("Native premaster decode failed: " + error)
    source = FloatMasterInput(str(request.premaster), request.samples, measured, ffmpeg, request.profile)
    master, chain, note, decision = render_float_master(source, request.directory)
    receipt.update(masteringFilter=chain, masteringNote=note, masteringDecision=decision,
        masteringPolicyVersion=MASTERING_POLICY_VERSION,
        masterClock=exact_float_audio_clock(str(master), ffprobe, request.samples),
        masterDelivery=measure_delivery(str(master)), masterSha256=file_sha256(str(master)))
    if not receipt["masterDelivery"]["qualified"]:
        raise RuntimeError("Native float master failed shared delivery targets")
    return master


def _encode(request: NativeDialogueDelivery, master: Path, receipt: dict,
            tools: tuple[str, str]) -> Path:
    """Copy the exact completed picture and encode the float master to AAC once."""
    ffmpeg, ffprobe = tools
    picture = observe_picture_source(str(request.picture), request.samples / 48000, request.picture_sha256)
    candidate = request.directory / "candidate.mp4"
    audio_options = native_aac_arguments(request.profile, receipt)
    receipt["aacEncodeInvocations"] = 1
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-n",
        "-i", picture.path, "-i", str(master), "-map", "0:v:0", "-c:v", "copy",
        "-map", "1:a:0", "-af", f"atrim=end_sample={request.samples},asetpts=PTS-STARTPTS",
        *audio_options,
        "-video_track_timescale", str(picture.time_base.denominator), "-movie_timescale", "48000",
        "-movflags", ENCODE["movflags"], str(candidate)])
    receipt["aacEncodesCompleted"] = 1
    return _qualify(request, master, receipt, tools)


def _qualify(request: NativeDialogueDelivery, master: Path, receipt: dict,
             tools: tuple[str, str]) -> Path:
    """Apply identical actual output gates to fresh and reused encoded dialogue."""
    ffmpeg, ffprobe = tools
    picture = observe_picture_source(str(request.picture), request.samples / 48000, request.picture_sha256)
    candidate = request.directory / "candidate.mp4"
    receipt.update(picture=verify_picture_copy(picture, str(candidate)),
        audioClock=exact_aac_audio_clock(str(candidate), ffprobe, request.samples),
        candidateSha256=file_sha256(str(candidate)))
    reference = FloatDeliveryReference(str(master), request.samples, ffmpeg)
    receipt["signal"] = verify_float_delivery_signal(reference, str(candidate))
    receipt["delivery"] = measure_delivery(str(candidate))
    quality_plan = {"audioReviewSections": list(request.review_sections)} if request.review_sections else {}
    checks = check_audio_quality(str(candidate), quality_plan)
    receipt["audioQuality"] = [dict(name=row.name, status=row.status, measured=row.measured,
                                    detail=row.detail) for row in checks]
    receipt["audioReviewRequired"] = any(row.status == WARN for row in checks)
    if file_sha256(str(master)) != receipt["masterSha256"] \
            or file_sha256(str(candidate)) != receipt["candidateSha256"]:
        raise RuntimeError("Native master or candidate changed during qualification")
    if any(row.status == FAIL for row in checks):
        raise RuntimeError("Native AAC failed shared audio quality checks; see audioQuality evidence")
    if not receipt["delivery"]["qualified"]:
        raise NativeAacDeliveryError("Native AAC failed shared delivery targets")
    return candidate


def _reuse(request: NativeDialogueDelivery, receipt: dict, tools: tuple[str, str]) -> Path:
    """Reuse proved encoded dialogue only when its intended float input and policy match."""
    prior_path = request.prior_receipt
    if prior_path is None:
        raise ValueError("Native dialogue reuse requires its actual prior receipt")
    admitted = admit_audio_donor(prior_path, (request.premaster, request.premaster_sha256),
                                 request.samples, request.profile)
    prior, prior_hash = admitted.prior, admitted.sha256
    effective_profile, master, donor = admitted.profile, admitted.master, admitted.candidate
    receipt['aacEncodingPolicy'] = admitted.aac_policy
    if request.prepared_donor is not None:
        receipt['preparedDonorReceiptSha256'] = verify_prepared_donor(request, admitted)
    ffmpeg, ffprobe = tools
    receipt["premasterClock"] = exact_float_audio_clock(str(request.premaster), ffprobe, request.samples)
    destination = request.directory / "program-master.wav"
    shutil.copyfile(master, destination)
    for key in ("masteringFilter", "masteringNote", "masteringPolicyVersion", "masterSha256"):
        receipt[key] = prior[key]
    if "masteringDecision" in prior:
        receipt["masteringDecision"] = prior["masteringDecision"]
    receipt.update(masterClock=exact_float_audio_clock(str(destination), ffprobe, request.samples),
        masterDelivery=measure_delivery(str(destination)), reusedAudioReceiptSha256=prior_hash,
        additionalAacEncodes=0, masteringProfile=effective_profile.receipt())
    for key in ("aacCandidatePolicy", "aacCandidates", "encodingCandidateSha256"):
        if key in prior:
            receipt[key] = prior[key]
    receipt["aacCandidateOrigin"] = "reused-qualified-audio"
    if not receipt["masterDelivery"]["qualified"]:
        raise RuntimeError("Reused float master fails current delivery targets")
    picture = observe_picture_source(str(request.picture), request.samples / 48000, request.picture_sha256)
    candidate = request.directory / "candidate.mp4"
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-n", "-i", picture.path,
        "-i", str(donor), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
        "-video_track_timescale", str(picture.time_base.denominator), "-movie_timescale", "48000",
        "-movflags", ENCODE["movflags"], str(candidate)])
    if packet_signature(str(donor), "a:0") != packet_signature(str(candidate), "a:0"):
        raise RuntimeError("Reused AAC packets or their exact presentation clock changed")
    result = _qualify(request, destination, receipt, tools)
    verify_audio_donor(admitted)
    receipt["aacPacketsReused"] = True
    return result


def _retain_attempt(request: NativeDialogueDelivery, receipt: dict, attempt: dict) -> None:
    """Persist failed and passing lossless/AAC evidence without overwriting another attempt."""
    (request.directory / "receipt.json").write_text(json.dumps(attempt, indent=2, allow_nan=False) + "\n")
    for key in ("masteringProfile", "masteringFilter", "masteringNote", "masteringDecision", "masteringPolicyVersion",
                "premasterClock", "masterClock", "masterDelivery", "masterSha256", "picture",
                "audioClock", "signal", "delivery", "candidateSha256", "aacEncodingPolicy",
                "audioQuality", "audioReviewRequired"):
        if key in attempt:
            receipt[key] = attempt[key]
    receipt["additionalAacEncodes"] = sum(row.get("aacEncodesCompleted", 0) for row in receipt["aacCandidates"])
    receipt["totalAacEncodeInvocations"] = sum(row.get("aacEncodeInvocations", 0) for row in receipt["aacCandidates"])


def _promote_candidate(request: NativeDialogueDelivery, attempt: dict) -> Path:
    """Copy qualified float/AAC bytes to stable delivery names without another encode."""
    for name, key in (("program-master.wav", "masterSha256"), ("candidate.mp4", "candidateSha256")):
        source, destination = Path(attempt["directory"]) / name, request.directory / name
        if destination.exists() or file_sha256(str(source)) != attempt[key]:
            raise RuntimeError("Native selected candidate changed or destination already exists")
        shutil.copyfile(source, destination)
        if file_sha256(str(destination)) != attempt[key] or file_sha256(str(source)) != attempt[key]:
            raise RuntimeError("Native selected candidate changed during promotion")
    return request.directory / "candidate.mp4"


def _record_attempt_failure(attempt: dict, error: Exception) -> None:
    """Preserve an earlier structural/signal failure instead of disguising it as codec peak excess."""
    attempt.update(status="failed", error=str(error))
    if isinstance(error, ProgramDeliverySignalError):
        attempt["signal"] = error.evidence


def _finish_candidates(request: NativeDialogueDelivery, receipt: dict, tools: tuple[str, str]) -> Path:
    """Remaster unchanged float input only for bounded true-peak-only AAC failures."""
    receipt.update(aacCandidatePolicy=dict(AAC_PEAK_CANDIDATE_POLICY), aacCandidates=[], aacCandidateOrigin="current-run")
    profile = request.profile
    for index in range(1, AAC_PEAK_CANDIDATE_POLICY["maximumCandidates"] + 1):
        _stable(request)
        directory = request.directory / f"attempt-{index:02d}"
        directory.mkdir(exist_ok=False)
        current = replace(request, directory=directory, profile=profile,
                          prepared_master=request.prepared_master if index == 1 else None)
        attempt = dict(candidateIndex=index, directory=str(directory), status="incomplete",
            masteringProfile=profile.receipt(), inputPremasterSha256=request.premaster_sha256,
            aacEncodeInvocations=0, aacEncodesCompleted=0)
        receipt["aacCandidates"].append(attempt)
        try:
            master = _master(current, attempt, tools)
            _encode(current, master, attempt, tools)
            attempt["status"] = "audio-qualified"
        except NativeAacDeliveryError as error:
            _record_attempt_failure(attempt, error)
            profile = corrected_peak_profile(profile, attempt.get("delivery"), index)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            _record_attempt_failure(attempt, error)
            raise
        finally:
            _retain_attempt(current, receipt, attempt)
        if attempt["status"] == "audio-qualified":
            receipt["encodingCandidateSha256"] = attempt["candidateSha256"]
            return _promote_candidate(request, attempt)
    raise RuntimeError("Native AAC candidate budget exhausted")


def finish_native_dialogue(request: NativeDialogueDelivery) -> dict:
    """Retain successful and failed candidates; never imply creative/publish approval."""
    request.directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = dict(schemaVersion=1, scope="native-dialogue-audio-qualification-only",
        status="incomplete", approved=False, humanListeningApproved=False,
        inputPictureSha256=request.picture_sha256, inputPremasterSha256=request.premaster_sha256,
        masteringProfile=request.profile.receipt(), requestedMasteringProfile=request.profile.receipt(),
        aacEncodingPolicy=native_aac_encoding_policy(request.profile),
        additionalPictureEncodes=0, audiblePathAacEncodes=1, additionalAacEncodes=0,
        totalAacEncodeInvocations=0)
    try:
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("Native delivery requires installed FFmpeg and ffprobe")
        _stable(request)
        if request.prior_receipt is not None:
            candidate = _reuse(request, receipt, (ffmpeg, ffprobe))
        else:
            candidate = _finish_candidates(request, receipt, (ffmpeg, ffprobe))
        _stable(request)
        receipt.update(status="audio-qualified", output=str(candidate))
        return receipt
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        receipt.update(status="failed", error=str(error))
        if isinstance(error, ProgramDeliverySignalError):
            receipt["signal"] = error.evidence
        LOGGER.error("Native dialogue finishing failed: %s", error)
        raise
    finally:
        receipt["elapsedSeconds"] = time.monotonic() - started
        (request.directory / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
