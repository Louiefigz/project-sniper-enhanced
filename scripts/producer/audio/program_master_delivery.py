"""Encode one retained full-program master to AAC without retiming picture."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.audio_mix_delivery import render_qualified_mix
from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from audio.program_master_bus import ProgramMaster, verify_program_master
from audio.render_audio_authority import run_audio, seal_audio_record
from audio.program_audio_clock import aac_audio_clock
from audio.program_delivery_signal import verify_program_delivery_signal
from cut_preview_io import MAX_MEDIA, file_hash, real_directory
from producer_config import ENCODE


@dataclass(frozen=True)
class ProgramDeliveryRequest:
    """Explicit output paths and one caller-owned media read budget."""

    picture_path: str
    output_path: str
    maximum_media_bytes: int = MAX_MEDIA

    def __post_init__(self) -> None:
        """Reject invalid limits before verifying or rendering any media."""
        if type(self.maximum_media_bytes) is not int or self.maximum_media_bytes <= 0:
            raise ValueError("program delivery media budget must be a positive integer")


def _encode(candidate: str, context: tuple) -> dict:
    """No normalization here: encode the exact previously mastered full bus."""
    master, plan, picture, maximum_media_bytes = context
    bus = master.source_bus
    try:
        verify_program_master(master, plan)
        run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error",
            "-xerror", "-err_detect", "explode", "-n", "-i", picture.path, "-i", master.path,
            "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0",
            "-af", f"atrim=end_sample={bus.samples},asetpts=PTS-STARTPTS",
            "-c:a", "aac", "-b:a", ENCODE["audio_bitrate"], "-ar", "48000", "-ac", "2",
            "-video_track_timescale", str(picture.time_base.denominator),
            "-movie_timescale", "48000", "-movflags", ENCODE["movflags"], candidate])
        file_hash(Path(candidate).absolute(), maximum_media_bytes)
        picture_proof = verify_picture_copy(picture, candidate)
        audio_clock = aac_audio_clock(candidate, bus)
        local_signal = verify_program_delivery_signal(master, candidate, maximum_media_bytes)
        verify_program_master(master, plan)
        return {"ok": True, "stderr": "", "picture": picture_proof, "audioClock": audio_clock,
                "localSignal": local_signal,
                "expectedCandidateSha256": local_signal["candidateSha256"],
                "mastering_note": master.receipt["masteringNote"]}
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        return {"ok": False, "stderr": str(error), "localSignal": getattr(error, "evidence", None)}


def deliver_program_master(master: ProgramMaster, plan: dict,
                           paths: tuple[str, str] | ProgramDeliveryRequest,
                           receipt_root: Path | None = None) -> dict:
    """Qualify actual AAC and picture bytes before replacing the requested output."""
    request = paths if isinstance(paths, ProgramDeliveryRequest) else ProgramDeliveryRequest(*paths)
    picture_path, output = request.picture_path, request.output_path
    picture_sha256 = file_hash(Path(picture_path).absolute(), request.maximum_media_bytes)
    bus = master.source_bus
    verify_program_master(master, plan)
    root = receipt_root if receipt_root is not None else Path(master.directory)
    real_directory(root)
    if receipt_root is not None and root != Path(output).absolute().parent:
        raise RuntimeError("private delivery receipts must remain beside their candidate output")
    directory = Path(tempfile.mkdtemp(prefix=".delivery-v2-", dir=root))
    picture = observe_picture_source(picture_path,
        float(Fraction(bus.frames, 1) / Fraction(bus.frame_rate)), picture_sha256)
    result = render_qualified_mix(output, lambda candidate: _encode(
        candidate, (master, plan, picture, request.maximum_media_bytes)))
    if not result["ok"]:
        seal_audio_record(str(directory / "delivery-failed.json"), {"schemaVersion": 2,
            "kind": "ordinary-program-delivery-failed", "approved": False, "result": result})
        raise RuntimeError(f"source-float full-program delivery unqualified: {result}")
    body = {"schemaVersion": 2, "kind": "ordinary-program-delivery", "approved": False,
        "audioClockPolicy": bus.admission.policy, "programMasterReceiptHash": master.receipt["receiptHash"],
        "audioProgramInputHash": master.receipt["audioProgramInputHash"],
        "path": str(Path(output).absolute()),
        "sha256": file_hash(Path(output).absolute(), request.maximum_media_bytes),
        "picture": result["picture"], "audioClock": result["audioClock"],
        "localSignal": result["localSignal"],
        "delivery": result["delivery"], "audiblePathAacEncodes": 1,
        "legacyPictureTransportAacStillExecuted": True}
    receipt = seal_audio_record(str(directory / "delivery-receipt.json"), body)
    return {**result, "programMasterReceiptPath": str(Path(master.directory) / "master-receipt.json"),
            "programMasterReceiptHash": master.receipt["receiptHash"], "deliveryReceiptHash": receipt["receiptHash"],
            "deliveryReceiptPath": str(directory / "delivery-receipt.json")}
