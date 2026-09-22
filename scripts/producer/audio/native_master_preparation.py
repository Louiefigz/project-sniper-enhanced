"""Qualify the same float master before picture; retain all final AAC/mux checks."""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from audio.mastering_profile import MasteringProfile
from audit.audio_quality import check_audio_program_quality
from audit.audit_checks import FAIL, PASS, WARN
from cut_preview_io import bound_json, file_hash, write_new
from producer_config import MASTERING_POLICY_VERSION

if TYPE_CHECKING:
    from audio.native_dialogue_delivery import NativeDialogueDelivery

LOGGER = logging.getLogger(__name__)
MASTER_FIELDS = ("premasterClock", "masteringFilter", "masteringNote",
                 "masteringPolicyVersion", "masterClock", "masterDelivery", "masterSha256")


@dataclass(frozen=True)
class NativeMasterPreparation:
    """Only audio inputs; an unfinished picture is never invented as authority."""

    premaster: Path
    premaster_sha256: str
    samples: int
    directory: Path
    profile: MasteringProfile
    review_sections: tuple[dict, ...] = ()
    prepared_master: tuple[Path, str] | None = None


def prepare_native_master(request: NativeMasterPreparation, tools: tuple[str, str]) -> tuple[Path, str]:
    """Materialize once through shared mastering and reject bad audio before picture."""
    from audio.native_dialogue_delivery import _master
    request.directory.mkdir(exist_ok=False)
    record = {"schemaVersion": 1, "status": "incomplete", "humanListeningApproved": False,
              "inputPremasterSha256": request.premaster_sha256, "samples": request.samples,
              "masteringProfile": request.profile.receipt(),
              "reviewSections": list(request.review_sections), "additionalAacEncodes": 0}
    path = request.directory / "receipt.json"
    try:
        _stable_input(request)
        master = _master(request, record, tools)
        plan = {"audioReviewSections": list(request.review_sections)} if request.review_sections else {}
        checks = check_audio_program_quality(str(master), plan)
        record["audioQuality"] = [dict(name=row.name, status=row.status, measured=row.measured,
                                       detail=row.detail) for row in checks]
        record["audioReviewRequired"] = any(row.status == WARN for row in checks)
        if any(row.status == FAIL for row in checks):
            raise RuntimeError("Early native float master failed shared audio quality checks")
        _stable_input(request)
        if file_hash(master) != record["masterSha256"]:
            raise RuntimeError("Early native master changed during checks")
        record.update(status="float-master-checked-awaiting-aac", output=str(master))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error))
        LOGGER.error("Early native audio preparation failed: %s", error)
        raise
    finally:
        write_new(path, record)
    return path, file_hash(path)


def _stable_input(request: NativeMasterPreparation | NativeDialogueDelivery) -> None:
    """Reject source mutation before accepting or reusing a measured master."""
    if file_hash(request.premaster) != request.premaster_sha256:
        raise RuntimeError("Native premaster changed during early preparation")


def _read_preparation(request: NativeDialogueDelivery) -> tuple[dict, Path]:
    """Require exact input, clock, profile and current quality evidence."""
    path, expected = request.prepared_master
    record = bound_json(path, expected)
    valid = record.get("status") == "float-master-checked-awaiting-aac" \
        and record.get("inputPremasterSha256") == request.premaster_sha256 \
        and type(record.get("samples")) is int and record["samples"] == request.samples \
        and record.get("masteringProfile") == request.profile.receipt() \
        and record.get("masteringPolicyVersion") == MASTERING_POLICY_VERSION \
        and record.get("reviewSections") == list(request.review_sections) \
        and record.get("masterDelivery", {}).get("qualified") is True
    checks = record.get("audioQuality")
    if not valid or not isinstance(checks, list) or not checks \
            or any(not isinstance(row, dict) or row.get("status") not in (PASS, WARN) for row in checks) \
            or any(key not in record for key in MASTER_FIELDS):
        raise RuntimeError("Early native master lacks matching policy, source, clock or quality")
    master = path.parent / "program-master.wav"
    if record.get("output") != str(master) or file_hash(master) != record["masterSha256"]:
        raise RuntimeError("Early native master bytes changed")
    return record, master


def reuse_prepared_master(request: NativeDialogueDelivery, receipt: dict,
                         tools: tuple[str, str]) -> Path:
    """Copy the admitted float bytes; all encoded delivery gates still execute."""
    from audio.program_audio_clock import exact_float_audio_clock
    _stable_input(request)
    record, master = _read_preparation(request)
    destination = request.directory / "program-master.wav"
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Prepared native master destination must be new")
    with destination.open("xb") as target, master.open("rb") as source:
        shutil.copyfileobj(source, target)
    if file_hash(destination) != record["masterSha256"]:
        raise RuntimeError("Prepared native master copy changed")
    _read_preparation(request)
    _stable_input(request)
    receipt.update({key: record[key] for key in MASTER_FIELDS})
    if "masteringDecision" in record:
        receipt["masteringDecision"] = record["masteringDecision"]
    receipt.update(masterClock=exact_float_audio_clock(str(destination), tools[1], request.samples),
                   preparedMasterReceiptSha256=request.prepared_master[1])
    return destination
