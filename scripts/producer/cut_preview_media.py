"""Strict browser/clock/decode observations for a non-delivery cut preview."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from cut_speed import decide_profile, proxy_profile
from cut_preview_io import MAX_MEDIA, file_hash, run_bounded


def probe(path: Path, executable: str) -> dict:
    """Decode-count streams using the tool whose executable bytes are bound."""
    result = run_bounded([
        executable, "-v", "error", "-count_frames", "-show_streams",
        "-show_format", "-of", "json", str(path),
    ], maximum=1024 * 1024)
    if result.returncode or result.stderr.strip() or len(result.stdout) > 1024 * 1024:
        raise RuntimeError("cut preview stream probe failed or exceeded its bound")
    return json.loads(result.stdout)


def render_profile(plan: dict, manifest: dict, scale: float) -> dict:
    """Preserve the source aspect/FPS; fail closed for unqualified HDR formats."""
    source = next(row for row in manifest["sources"]
                  if row["id"] == plan["cutTrack"][0]["sourceId"])
    full = decide_profile(source["path"])
    scale = min(scale, 960 / max(full.width, full.height))
    profile = proxy_profile(full, scale)
    if profile.pix_fmt != "yuv420p" or max(profile.width, profile.height) > 1280 \
            or not 1 <= float(profile.fps) <= 60:
        raise RuntimeError("cut preview requires qualified SDR yuv420p at <=1280px/60fps; no implicit tone mapping")
    return {"width": profile.width, "height": profile.height,
            "fps": profile.fps_arg, "pixFmt": profile.pix_fmt,
            "proxyScale": scale}


def reject_hdr(manifest: dict, ffprobe: str) -> None:
    """Check every source, not just the first source's output profile."""
    for row in manifest["sources"]:
        result = run_bounded([ffprobe, "-v", "error", "-select_streams", "v:0",
                                 "-show_streams", "-of", "json", row["path"]],
                                maximum=1024 * 1024, timeout=30)
        if result.returncode or result.stderr.strip() or len(result.stdout) > 1024 * 1024:
            raise RuntimeError("cut preview source-color observation failed")
        streams = json.loads(result.stdout).get("streams", [])
        if len(streams) != 1 or streams[0].get("pix_fmt") != "yuv420p" \
                or streams[0].get("color_transfer") in {"smpte2084", "arib-std-b67"} \
                or streams[0].get("color_primaries") in {"bt2020"}:
            raise RuntimeError("cut preview source color is not qualified SDR; no implicit tone mapping")


def _decode_pcm(path: Path, ffmpeg: str) -> int:
    """Strictly decode all video plus presented audio; count exact PCM samples."""
    command = [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
               "-i", str(path), "-map", "0:v:0", "-f", "null", os.devnull,
               "-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=errors)
        assert child.stdout is not None
        count = 0
        while data := child.stdout.read(1024 * 1024):
            count += len(data)
            if count > MAX_MEDIA:
                child.kill()
                child.wait(timeout=5)
                raise RuntimeError("cut preview PCM decode exceeded its byte bound")
        child.stdout.close()
        code = child.wait(timeout=30)
        errors.seek(0)
        detail = errors.read(4097)
    if code or detail or count <= 0 or count % 4:
        raise RuntimeError("cut preview strict full decode failed")
    return count // 4


def _audio(stream: dict, samples: int, video_samples: int) -> dict:
    """Retain AAC presentation clock and decoded trailing padding explicitly."""
    if stream.get("codec_name") != "aac" or stream.get("sample_rate") != "48000" \
            or stream.get("channels") != 2 or stream.get("channel_layout") != "stereo":
        raise RuntimeError("cut preview audio is not browser-compatible 48k stereo AAC")
    base = Fraction(stream["time_base"])
    presented = Fraction(int(stream["duration_ts"])) * base * 48000
    if presented.denominator != 1:
        raise RuntimeError("cut preview AAC presentation has a fractional sample clock")
    count = int(presented)
    if not 0 <= samples - count <= 2048 or abs(count - video_samples) > 1024 \
            or int(stream.get("start_pts", -1)) != 0:
        raise RuntimeError("cut preview AAC presentation/decoded padding diverges from video: "
                           f"decoded={samples}, presented={count}, video={video_samples}, "
                           f"startPts={stream.get('start_pts')}")
    return {"codec": "aac", "sampleRate": 48000, "channels": 2,
            "channelLayout": "stereo", "timeBase": stream["time_base"],
            "startPts": 0, "durationTs": int(stream["duration_ts"]),
            "decodedAudioSamples": samples, "presentedAudioSamples": count,
            "trailingPaddingSamples": samples - count,
            "presentationVsVideoSamples": count - video_samples,
            "trimPolicy": "ffmpeg-mp4-edit-list"}


def observe_media(path: Path, profile: dict, tools: dict,
                  maximum_media_bytes: int = MAX_MEDIA) -> dict:
    """Validate actual bytes, frame count, browser streams and full A/V decode."""
    before = file_hash(path, maximum_media_bytes)
    document = probe(path, tools["ffprobe"])
    streams = document.get("streams", [])
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    if len(streams) != 2 or len(videos) != 1 or len(audios) != 1:
        raise RuntimeError("cut preview must contain exactly one video and one audio stream")
    video = videos[0]
    frames = int(video.get("nb_read_frames", 0))
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p" \
            or video.get("width") != profile["width"] or video.get("height") != profile["height"] \
            or Fraction(video["r_frame_rate"]) != Fraction(profile["fps"]) \
            or Fraction(video["avg_frame_rate"]) != Fraction(profile["fps"]) \
            or int(video.get("start_pts", -1)) != 0 or frames <= 0:
        raise RuntimeError("cut preview video differs from its browser/CFR profile: "
                           + json.dumps({key: video.get(key) for key in ("codec_name", "pix_fmt",
                               "width", "height", "r_frame_rate", "avg_frame_rate", "start_pts", "nb_read_frames")}))
    samples = _decode_pcm(path, tools["ffmpeg"])
    audio = _audio(audios[0], samples, round(Fraction(frames, 1) / Fraction(profile["fps"]) * 48000))
    if before != file_hash(path, maximum_media_bytes):
        raise RuntimeError("cut preview media changed during full decode")
    return {"name": "cut-preview.mp4", "sha256": before, "sizeBytes": path.stat().st_size,
            "videoCodec": "h264", "pixFmt": "yuv420p", "videoFrames": frames,
            "audio": audio, "fullDecode": "passed"}
