"""Qualified AAC without-music delivery, never a PCM-in-MP4 stem export."""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from fractions import Fraction

from audio.audio_mix_delivery import measure_delivery, render_qualified_mix
from audio.audio_mix_picture import packet_signature as _packet_signature
from audio.channel_normalization import ChannelAuthority, ChannelNormalizationError
from audio.master import select_pass2_filter, measure_loudness
from fingerprints import file_sha256
from producer_config import ENCODE


@dataclass(frozen=True)
class WithoutDeliveryPlan:
    """A preflighted source, immutable byte identity, and delivery route."""

    source_path: str
    source_sha256: str
    duration: float
    copy_aac: bool
    picture_path: str
    picture_sha256: str


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _probe(path: str) -> dict:
    result = _run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path])
    try:
        streams = json.loads(result.stdout)["streams"]
        video = [row for row in streams if row.get("codec_type") == "video"]
        audio = [row for row in streams if row.get("codec_type") == "audio"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ChannelNormalizationError("without-music media probe failed") from exc
    if result.returncode or not video or not audio:
        raise ChannelNormalizationError("without-music media lacks picture or audio")
    return {"video": video[0], "audio": audio[0]}


def _aac_shape(row: dict, duration: float) -> bool:
    """Require configured stereo AAC and the picture-owned presented clock."""
    try:
        rate = int(row["sample_rate"])
        presented = int(row["duration_ts"]) * Fraction(row["time_base"]) * rate
        start = Fraction(row.get("start_time", "0"))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    return (row.get("codec_name") == ENCODE["acodec"]
            and rate == ENCODE["audio_rate"] and row.get("channels") == 2
            and row.get("channel_layout") == "stereo" and start == 0
            and abs(float(presented) - duration * rate) <= 1)


def without_headroom_error(path: str) -> str | None:
    """Reject an over-range raw input before any requested delivery is written."""
    measured = measure_loudness(path)
    try:
        peak = float((measured or {})["input_tp"])
    except (KeyError, TypeError, ValueError):
        return "without-music headroom could not be proved"
    if math.isnan(peak) or peak > 0:
        return "without-music delivery rejects over-range audio; master the program first"
    return None


def prepare_without_delivery(authority: ChannelAuthority, normalized: str,
                              duration: float) -> WithoutDeliveryPlan:
    """Copy original AAC only when channel, clock, and delivery checks permit."""
    error = without_headroom_error(normalized)
    if error:
        raise ChannelNormalizationError(error)
    authority.assert_stable()
    original = authority.request.source_path
    decision = authority.receipt["decision"]["status"]  # type: ignore[index]
    copy = decision == "stereo-verified" and _aac_shape(_probe(original)["audio"], duration)
    copy = bool(copy and measure_delivery(original)["qualified"])
    source = original if copy else normalized
    return WithoutDeliveryPlan(source, file_sha256(source), duration, copy,
                               original, authority.request.source_sha256)


def _verify_media(plan: WithoutDeliveryPlan, candidate: str) -> dict:
    """Prove browser codec shape and unchanged picture; copied AAC is byte exact."""
    if not _aac_shape(_probe(candidate)["audio"], plan.duration):
        raise ChannelNormalizationError("without-music AAC sample clock or format drifted")
    before = _packet_signature(plan.picture_path, "v:0")
    if before != _packet_signature(candidate, "v:0"):
        raise ChannelNormalizationError("without-music picture packets or PTS drifted")
    if plan.copy_aac and _packet_signature(plan.source_path, "a:0") \
            != _packet_signature(candidate, "a:0"):
        raise ChannelNormalizationError("without-music copied AAC packets or trim timing drifted")
    return {"policyVersion": 2, "codec": "aac", "sampleRate": ENCODE["audio_rate"],
            "channels": 2, "picturePackets": len(before), "picturePacketsIdentical": True,
            "route": "verified-original-aac-copy" if plan.copy_aac else "qualified-aac-encode"}


def _render_candidate(plan: WithoutDeliveryPlan, candidate: str) -> dict:
    """Copy picture; encode only audio when original AAC cannot safely pass through."""
    if not _sources_stable(plan):
        return {"ok": False, "stderr": "without-music source bytes changed after preflight"}
    command = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", plan.picture_path]
    if not plan.copy_aac:
        command += ["-i", plan.source_path]
    command += ["-map", "0:v:0", "-c:v", "copy", "-map",
                "0:a:0" if plan.copy_aac else "1:a:0"]
    note, decision = None, None
    if plan.copy_aac:
        command += ["-c:a", "copy"]
    else:
        selected = select_pass2_filter(
            plan.source_path, None, measure_loudness(plan.source_path))
        note, decision = selected.note, selected.evidence
        command += ["-af", selected.chain, "-c:a", ENCODE["acodec"],
                    "-b:a", ENCODE["audio_bitrate"], "-ar", str(ENCODE["audio_rate"]),
                    "-ac", "2", "-t", f"{plan.duration:.6f}"]
    time_base = Fraction(_probe(plan.picture_path)["video"]["time_base"])
    command += ["-video_track_timescale", str(time_base.denominator),
                "-movflags", ENCODE["movflags"], candidate]
    result = _run(command)
    if result.returncode:
        return {"ok": False, "stderr": result.stderr[-800:]}
    if not _sources_stable(plan):
        return {"ok": False, "stderr": "without-music source bytes changed during rendering"}
    try:
        proof = _verify_media(plan, candidate)
    except ChannelNormalizationError as exc:
        return {"ok": False, "stderr": str(exc)}
    return {"ok": True, "stderr": "", "media": proof, "mastering_note": note,
            "mastering_decision": decision}


def _sources_stable(plan: WithoutDeliveryPlan) -> bool:
    """Check each distinct held audio/picture snapshot before and after use."""
    sources = {(plan.source_path, plan.source_sha256),
               (plan.picture_path, plan.picture_sha256)}
    return all(file_sha256(path) == expected for path, expected in sources)


def render_without_delivery(plan: WithoutDeliveryPlan, destination: str) -> dict:
    """Publish only measured, AAC-compatible without-music delivery bytes."""
    return render_qualified_mix(destination, lambda candidate: _render_candidate(plan, candidate))
