#!/usr/bin/env python3
"""Transcribe clips with Deepgram or fail-closed local whisper.cpp."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from deepgram import AsyncDeepgramClient

import numpy as np

# shared transcription modules live at scripts/ root, one level up
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asr_policy import paid_deepgram_client, require_paid_asr, run_asr_cli  # noqa: E402
from local_whisper import (DEEPGRAM_PROVIDER, LOCAL_PROVIDER,  # noqa: E402
                           LocalTranscribeRequest, LocalWhisperError,
                           transcribe_media, transcription_provider)

_SNIPER_DEBUG = os.environ.get("SNIPER_DEBUG") != "0"


def dbg(scope: str, event: str, **data):
    if not _SNIPER_DEBUG:
        return
    try:
        extra = json.dumps(data, default=str)
    except Exception:
        extra = str(data)
    if len(extra) > 1500:
        extra = extra[:1500] + f"… (+{len(extra) - 1500} more chars)"
    print(f"[SNIPER:{scope}] {event} {extra}", file=sys.stderr, flush=True)


MAX_DEEPGRAM_FILE_SIZE = 25 * 1024 * 1024  # 25MB upload limit
CHUNK_DURATION_SECONDS = 600  # 10 minutes per chunk
FRAGMENT_TEMPLATE = "chunk-%03d.mp3"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

# --- Lav cross-talk suppression -------------------------------------------------
# Each lav mic faintly picks up the OTHER speaker (bleed). Because we transcribe
# each lav independently, that bleed is transcribed too — producing a duplicate of
# the other person's words on the wrong track. A word transcribed on a track is
# kept only when that track is the loudest at that moment; if the OTHER mic is
# louder by CROSSTALK_DOMINANCE×, the word is bleed and is dropped.
CROSSTALK_HOP = 800  # 50ms @ 16kHz — loudness-envelope resolution
# Keep each mic only where its owner is the louder of the two (an automix gate).
# 1.0 = silence a track wherever the other mic is louder. Raise (e.g. 1.3) only if
# real speech is being clipped; lower toward 0.8 if bleed still leaks through.
CROSSTALK_DOMINANCE = float(os.environ.get("CLIPPER_CROSSTALK_RATIO", "1.0"))
# OFF by default: lav-mic bleed is handled downstream (the export merges overlapping
# source ranges, and the edit prompt drops duplicate copies), which is far more robust
# than gating the audio. Set CLIPPER_CROSSTALK=1 to re-enable the experimental gate.
CROSSTALK_ENABLED = os.environ.get("CLIPPER_CROSSTALK") == "1"
CROSSTALK_HANGOVER = int(os.environ.get("CLIPPER_CROSSTALK_HANGOVER", "4"))  # ±windows (~200ms) kept around speech to avoid clipping word edges


def run_command(cmd: List[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Command failed")
    return result.stdout.strip()


def get_audio_metadata(audio_path: str) -> tuple[float, float]:
    """Get duration (seconds) and audio stream start_time via ffprobe."""
    output = run_command([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=start_time,codec_type",
        "-of", "json",
        audio_path,
    ])
    data = json.loads(output)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    # Find the audio stream start_time — can be non-zero in MP4s recorded by cameras
    start_time = 0.0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            val = stream.get("start_time")
            if val and val != "N/A":
                start_time = float(val)
            break
    return (start_time, duration)


def get_channel_count(path: str) -> int:
    """Return the number of audio channels in the first audio stream."""
    try:
        output = run_command([
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=channels",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ])
        return int(output.strip().split("\n")[0])
    except Exception:
        return 1


def _read_stereo_pcm(path: str, max_seconds: int = 300) -> Optional[np.ndarray]:
    """Decode up to max_seconds of audio as 16kHz stereo int16 PCM.

    Returns an (N, 2) int16 array, or None on any failure / non-stereo source.
    """
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error",
            "-i", path,
            "-t", str(max_seconds),
            "-vn", "-ac", "2", "-ar", "16000",
            "-f", "s16le", "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    samples = np.frombuffer(result.stdout, dtype=np.int16)
    if samples.size < 2 or samples.size % 2 != 0:
        return None
    return samples.reshape(-1, 2)


def is_channel_isolated(path: str, threshold: float = 0.65) -> bool:
    """True only when L and R envelopes are clearly complementary.

    Compares per-50ms-window RMS envelopes of L vs R via Pearson correlation.
    - Channel-isolated (host on L, caller on R): low corr (~0.2-0.5) -> True
    - Cross-talk stereo: high corr (~0.85-0.99) -> False
    - Mono-duplicated: corr ~1.0 -> False
    Any error / ambiguity returns False so the caller falls back to mono+diarize.
    """
    try:
        pcm = _read_stereo_pcm(path)
        if pcm is None or pcm.shape[0] < 16000 * 5:
            return False

        win = 800  # 50ms at 16kHz
        n_windows = pcm.shape[0] // win
        if n_windows < 50:
            return False

        framed = pcm[: n_windows * win].astype(np.float32).reshape(n_windows, win, 2)
        rms = np.sqrt((framed ** 2).mean(axis=1))
        left_env, right_env = rms[:, 0], rms[:, 1]

        noise_floor = max(50.0, 0.01 * float(rms.max()))
        voiced = (left_env > noise_floor) | (right_env > noise_floor)
        if voiced.sum() < 50:
            return False
        left_env = left_env[voiced]
        right_env = right_env[voiced]

        if left_env.std() < 1e-3 or right_env.std() < 1e-3:
            return False

        corr = float(np.corrcoef(left_env, right_env)[0, 1])
        if not np.isfinite(corr):
            return False

        return corr < threshold
    except Exception:
        return False


def _read_mono_pcm(path: str) -> Optional[np.ndarray]:
    """Decode a file fully as 16kHz mono int16 PCM. None on any failure."""
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    return np.frombuffer(result.stdout, dtype=np.int16)


def _envelope_from_pcm(pcm: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """Per-50ms RMS loudness envelope from mono int16 PCM; env[i] covers [i*hop,(i+1)*hop)."""
    if pcm is None or pcm.size < CROSSTALK_HOP:
        return None
    n = pcm.size // CROSSTALK_HOP
    framed = pcm[: n * CROSSTALK_HOP].astype(np.float32).reshape(n, CROSSTALK_HOP)
    return np.sqrt((framed ** 2).mean(axis=1))


def gate_track(pcm, this_env, other_env, noise_floor, label):
    """Silence the parts of `pcm` where the OTHER mic clearly dominates (= bleed of the
    other speaker). Returns a gated copy. Zeroing (not deleting) preserves the timeline,
    so Deepgram timestamps still line up with the video.

    Done BEFORE transcription so Deepgram only ever hears one speaker per track — this
    is what prevents bleed words and prevents both voices being merged into one utterance.
    """
    n = int(min(this_env.shape[0], other_env.shape[0]))
    te, oe = this_env[:n], other_env[:n]
    # A window is bleed (silence it) when the other mic is loud AND clearly louder here.
    silence = (oe > noise_floor) & (oe > te * CROSSTALK_DOMINANCE)
    keep = ~silence
    # Hangover: dilate kept regions by ±N windows so we don't clip the onset/tail of a
    # real word that sits next to a silenced span.
    if CROSSTALK_HANGOVER > 0 and keep.any():
        dilated = keep.copy()
        for s in range(1, CROSSTALK_HANGOVER + 1):
            dilated[s:] |= keep[:-s]
            dilated[:-s] |= keep[s:]
        keep = dilated
    mask = np.repeat(keep, CROSSTALK_HOP)
    gated = pcm.copy()
    m = int(min(mask.shape[0], gated.shape[0]))
    gated[:m] = np.where(mask[:m], gated[:m], np.int16(0))
    hop_s = CROSSTALK_HOP / 16000.0
    dbg("clipper", "gate.track", track=label, windows=n,
        kept_windows=int(keep.sum()), silenced_windows=int((~keep).sum()),
        kept_seconds=round(int(keep.sum()) * hop_s, 1),
        silenced_seconds=round(int((~keep).sum()) * hop_s, 1))
    return gated


def write_temp_wav(pcm: np.ndarray, sr: int = 16000) -> str:
    """Write mono int16 PCM to a temp WAV; caller must delete it."""
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="clipper-gated-")
    os.close(fd)
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return tmp


def extract_channel(video_path: str, channel: int) -> str:
    """Extract one stereo channel (0=left/host, 1=right/caller) as a mono MP3.

    Returns the path to a temporary file that the caller must delete.
    """
    channel_label = "FL" if channel == 0 else "FR"
    fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix=f"clipper-ch{channel}-")
    os.close(fd)
    result = subprocess.run(
        [
            "ffmpeg", "-i", video_path, "-vn",
            "-af", f"pan=mono|c0={channel_label}",
            "-ar", "16000", "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            tmp, "-y",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg channel {channel} extraction failed: {result.stderr.strip()}")
    return tmp


async def _transcribe_channel_deepgram(
    client: AsyncDeepgramClient,
    audio_path: str,
    speaker_id: int,
    audio_offset: float = 0.0,
) -> tuple[List[dict], Optional[str]]:
    """Transcribe a mono channel file.

    Returns (entries, detected_language).  All word-level speaker fields are
    set to speaker_id — diarization is disabled since we already know the speaker.
    """
    require_paid_asr()
    dbg("clipper", "channel.enter", audio_path=audio_path, speaker_id=speaker_id, audio_offset=audio_offset)
    chunk_paths, chunk_dir = split_audio_if_needed(audio_path)
    total_chunks = len(chunk_paths)
    offsets = get_chunk_offsets(audio_path, total_chunks) if total_chunks > 1 else [0.0]
    dbg("clipper", "channel.plan", speaker_id=speaker_id, total_chunks=total_chunks, offsets=offsets)

    entries: List[dict] = []
    detected_language: Optional[str] = None

    try:
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            with open(chunk_path, "rb") as f:
                audio_bytes = f.read()

            dbg("clipper", "deepgram.request", model="nova-3", diarize=False,
                speaker_id=speaker_id, chunk=idx, total=total_chunks, file=os.path.basename(chunk_path))
            _t0 = time.monotonic()
            require_paid_asr()
            response = await client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                model="nova-3",
                smart_format=True,
                punctuate=True,
                utterances=True,
                diarize=False,
                paragraphs=True,
            )

            chunk_data = response.model_dump()
            chunk_entries = build_transcript_entries(chunk_data, offsets[idx - 1] + audio_offset)
            _utts = chunk_data.get("results", {}).get("utterances") or []
            dbg("clipper", "deepgram.response", speaker_id=speaker_id, chunk=idx,
                num_utterances=len(_utts), num_entries=len(chunk_entries),
                num_words=sum(len(e.get("words", [])) for e in chunk_entries),
                elapsed_s=round(time.monotonic() - _t0, 2))

            # Stamp every word with the known speaker_id (channel-based, not diarized)
            for entry in chunk_entries:
                for word in entry.get("words", []):
                    word["speaker"] = speaker_id

            entries.extend(chunk_entries)

            if not detected_language:
                channels = chunk_data.get("results", {}).get("channels", [])
                if channels:
                    detected_language = channels[0].get("detected_language")
    finally:
        if chunk_dir and os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir)

    dbg("clipper", "channel.exit", speaker_id=speaker_id, num_entries=len(entries),
        num_words=sum(len(e.get("words", [])) for e in entries), language=detected_language)
    return entries, detected_language


async def transcribe_channel(
    client: Optional[AsyncDeepgramClient],
    audio_path: str,
    speaker_id: int,
    audio_offset: float = 0.0,
) -> tuple[List[dict], Optional[str]]:
    """Transcribe a known-speaker mono track with the configured provider."""
    if transcription_provider() == LOCAL_PROVIDER:
        request = LocalTranscribeRequest(
            path=audio_path, timeline_offset=audio_offset, speaker=speaker_id)
        result = await asyncio.to_thread(transcribe_media, request)
        return result["transcript"], result.get("language")
    if client is None:
        raise RuntimeError("Deepgram client missing for channel transcription")
    return await _transcribe_channel_deepgram(
        client, audio_path, speaker_id, audio_offset)


async def run_stereo_transcription(video_path: str, audio_offset: float = 0.0) -> None:
    """Transcribe isolated stereo by sending each channel separately.

    Left channel → speaker 0 (host), right channel → speaker 1 (caller).
    Entries from both channels are merged and sorted by start time.
    """
    dbg("clipper", "stereo.enter", video_path=video_path, audio_offset=audio_offset)
    _, duration = get_audio_metadata(video_path)

    print(json.dumps({"status": "extracting_channels"}), flush=True)
    left_path = extract_channel(video_path, 0)
    right_path = extract_channel(video_path, 1)
    size_mb = round((os.path.getsize(left_path) + os.path.getsize(right_path)) / (1024 * 1024), 1)
    dbg("clipper", "stereo.channels_extracted", left=left_path, right=right_path, size_mb=size_mb)
    print(json.dumps({"status": "audio_extracted", "size_mb": size_mb, "audio_offset": audio_offset}), flush=True)

    provider = transcription_provider()
    client = (paid_deepgram_client()
              if provider == DEEPGRAM_PROVIDER else None)
    detected_language: Optional[str] = None

    try:
        print(json.dumps({"status": "transcribing_chunk", "chunk": 1, "total": 2}), flush=True)
        left_entries, lang = await transcribe_channel(client, left_path, speaker_id=0, audio_offset=audio_offset)
        if lang:
            detected_language = lang

        print(json.dumps({"status": "transcribing_chunk", "chunk": 2, "total": 2}), flush=True)
        right_entries, lang = await transcribe_channel(client, right_path, speaker_id=1, audio_offset=audio_offset)
        if lang and not detected_language:
            detected_language = lang
    finally:
        for p in (left_path, right_path):
            if os.path.exists(p):
                os.unlink(p)

    transcript = sorted(left_entries + right_entries, key=lambda e: e["start"])
    duration_out = duration if duration > 0 else (transcript[-1]["end"] if transcript else 0)
    dbg("clipper", "stereo.exit", num_entries=len(transcript),
        duration=duration_out, language=detected_language or "en")

    print(
        json.dumps({
            "status": "done",
            "transcript": transcript,
            "duration": duration_out,
            "fps": 0,
            "language": detected_language or "en",
            "model": "deepgram:nova-3" if provider == DEEPGRAM_PROVIDER else "whisper.cpp:local",
        }),
        flush=True,
    )


async def run_lav_transcription(host_lav: str, guest_lav: str) -> None:
    """Transcribe two separate mono lav files: host (speaker 0) + guest (speaker 1).

    The lavs are already individual mics (one per person) and are pre-synced to the
    same timeline as the cameras, so there is no channel extraction and no Deepgram
    diarization — each file's speaker is known. Entries from both are merged and
    sorted by start time, exactly like the stereo path.

    The lav files are USER INPUTS, not producer-created temp files, so this function
    must NOT delete them (transcribe_channel still cleans its own chunk dirs).
    """
    # Each lav carries its own container start_time; correct intra-file timestamps
    # by that offset. (We do NOT align the two files to each other — they're
    # assumed pre-synced; cross-file alignment is SEGMENTER's job.)
    dbg("clipper", "lav.enter", host_lav=host_lav, guest_lav=guest_lav)
    host_offset, host_dur = get_audio_metadata(host_lav)
    guest_offset, guest_dur = get_audio_metadata(guest_lav)
    dbg("clipper", "lav.metadata", host_offset=host_offset, host_dur=host_dur,
        guest_offset=guest_offset, guest_dur=guest_dur)

    size_mb = round(
        (os.path.getsize(host_lav) + os.path.getsize(guest_lav)) / (1024 * 1024), 1
    )
    print(json.dumps({"status": "audio_extracted", "size_mb": size_mb, "audio_offset": host_offset}), flush=True)

    provider = transcription_provider()
    client = (paid_deepgram_client()
              if provider == DEEPGRAM_PROVIDER else None)
    detected_language: Optional[str] = None

    # --- Cross-talk gating (BEFORE transcription) ---------------------------------
    # Each mic bleeds the other speaker. We silence the bleed in each track's AUDIO
    # before sending it to Deepgram, so Deepgram only ever hears one speaker per track.
    # This prevents duplicate (bleed) words AND prevents both voices being stitched
    # into one utterance. We transcribe the gated WAVs; the raw lavs are untouched.
    host_in, guest_in = host_lav, guest_lav
    host_off_in, guest_off_in = host_offset, guest_offset
    gated_paths: List[str] = []
    if CROSSTALK_ENABLED:
        host_pcm = _read_mono_pcm(host_lav)
        guest_pcm = _read_mono_pcm(guest_lav)
        host_env = _envelope_from_pcm(host_pcm)
        guest_env = _envelope_from_pcm(guest_pcm)
        if host_pcm is not None and guest_pcm is not None and host_env is not None and guest_env is not None:
            noise_floor = max(50.0, 0.01 * max(float(host_env.max()), float(guest_env.max())))
            dbg("clipper", "gate.enter", host_env_hops=int(host_env.shape[0]),
                guest_env_hops=int(guest_env.shape[0]), noise_floor=round(noise_floor, 1),
                dominance=CROSSTALK_DOMINANCE, hangover=CROSSTALK_HANGOVER)
            host_gated = gate_track(host_pcm, host_env, guest_env, noise_floor, "host")
            guest_gated = gate_track(guest_pcm, guest_env, host_env, noise_floor, "guest")
            host_in = write_temp_wav(host_gated)
            guest_in = write_temp_wav(guest_gated)
            gated_paths = [host_in, guest_in]
            host_off_in = guest_off_in = 0.0  # fresh WAVs start at t=0
            dbg("clipper", "gate.written", host=host_in, guest=guest_in)
        else:
            dbg("clipper", "gate.skipped", reason="pcm/envelope decode failed",
                host_ok=host_pcm is not None, guest_ok=guest_pcm is not None)
    else:
        dbg("clipper", "gate.disabled", note="CLIPPER_CROSSTALK=0")

    try:
        print(json.dumps({"status": "transcribing_chunk", "chunk": 1, "total": 2}), flush=True)
        host_entries, lang = await transcribe_channel(client, host_in, speaker_id=0, audio_offset=host_off_in)
        if lang:
            detected_language = lang

        print(json.dumps({"status": "transcribing_chunk", "chunk": 2, "total": 2}), flush=True)
        guest_entries, lang = await transcribe_channel(client, guest_in, speaker_id=1, audio_offset=guest_off_in)
        if lang and not detected_language:
            detected_language = lang
    finally:
        # Gated WAVs are producer-owned temps; the raw lavs (user inputs) are never deleted.
        for p in gated_paths:
            if p and os.path.exists(p):
                os.unlink(p)

    transcript = sorted(host_entries + guest_entries, key=lambda e: e["start"])
    duration_out = max(host_dur, guest_dur)
    if duration_out <= 0:
        duration_out = transcript[-1]["end"] if transcript else 0
    dbg("clipper", "lav.exit", num_entries=len(transcript),
        duration=duration_out, language=detected_language or "en")

    print(
        json.dumps({
            "status": "done",
            "transcript": transcript,
            "duration": duration_out,
            "fps": 0,
            "language": detected_language or "en",
            "model": "deepgram:nova-3" if provider == DEEPGRAM_PROVIDER else "whisper.cpp:local",
        }),
        flush=True,
    )


def split_audio_if_needed(audio_path: str) -> tuple[List[str], Optional[str]]:
    size = os.path.getsize(audio_path)
    dbg("clipper", "split.check", audio_path=audio_path,
        size_mb=round(size / (1024 * 1024), 2), limit_mb=round(MAX_DEEPGRAM_FILE_SIZE / (1024 * 1024), 1))
    if size <= MAX_DEEPGRAM_FILE_SIZE:
        return [audio_path], None

    print(json.dumps({"status": "chunking_audio"}), flush=True)
    temp_dir = tempfile.mkdtemp(prefix="clipper-chunks-")
    pattern = os.path.join(temp_dir, FRAGMENT_TEMPLATE)
    subprocess.run(
        [
            "ffmpeg", "-i", audio_path,
            "-f", "segment",
            "-segment_time", str(CHUNK_DURATION_SECONDS),
            "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "16000", "-ac", "1",
            pattern, "-y",
        ],
        capture_output=True, check=True,
    )

    chunks = sorted(Path(temp_dir).glob("chunk-*.mp3"))
    if not chunks:
        raise RuntimeError("Chunking produced no files")

    chunk_paths = [str(c) for c in chunks]
    dbg("clipper", "split.chunks", count=len(chunk_paths),
        sizes_mb=[round(os.path.getsize(p) / (1024 * 1024), 2) for p in chunk_paths])
    print(json.dumps({"status": "chunking_complete", "chunks": len(chunk_paths)}), flush=True)
    return chunk_paths, temp_dir


def get_chunk_offsets(audio_path: str, num_chunks: int) -> List[float]:
    offsets: List[float] = []
    for i in range(num_chunks):
        target = i * CHUNK_DURATION_SECONDS
        if target == 0:
            offsets.append(0.0)
            continue
        try:
            output = run_command([
                "ffprobe", "-v", "error",
                "-read_intervals", f"{target}%+#1",
                "-show_entries", "packet=pts_time",
                "-select_streams", "a:0",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ])
            val = output.strip().split("\n")[0]
            offsets.append(float(val) if val and val != "N/A" else float(target))
        except Exception:
            offsets.append(float(target))
    return offsets


def build_transcript_entries(chunk_data: dict, offset: float) -> List[dict]:
    utterances = chunk_data.get("results", {}).get("utterances") or []
    if not utterances:
        channels = chunk_data.get("results", {}).get("channels", [])
        if channels:
            alt = (channels[0].get("alternatives") or [{}])[0]
            words = alt.get("words") or []
            utterances = [
                {
                    "start": words[0].get("start", 0) if words else 0,
                    "end": words[-1].get("end", 0) if words else 0,
                    "transcript": alt.get("transcript", ""),
                    "words": words,
                }
            ]

    entries: List[dict] = []
    for utt in utterances:
        raw_words = utt.get("words") or []
        entries.append(
            {
                "start": round((utt.get("start") or 0) + offset, 2),
                "end": round((utt.get("end") or 0) + offset, 2),
                "text": (utt.get("transcript") or "").strip(),
                "words": [
                    {
                        "word": word.get("punctuated_word") or word.get("word") or "",
                        "start": round((word.get("start") or 0) + offset, 3),
                        "end": round((word.get("end") or 0) + offset, 3),
                        "confidence": word.get("confidence"),
                        "speaker": word.get("speaker"),
                    }
                    for word in raw_words
                ],
            }
        )
    return entries


async def run_transcription(audio_path: str, audio_offset: float = 0.0) -> None:
    """Single async entry point — all Deepgram calls happen here."""
    require_paid_asr()
    dbg("clipper", "run.enter", audio_path=audio_path, audio_offset=audio_offset)
    _, duration = get_audio_metadata(audio_path)
    chunk_paths, chunk_dir = split_audio_if_needed(audio_path)
    total_chunks = len(chunk_paths)
    offsets = get_chunk_offsets(audio_path, total_chunks) if total_chunks > 1 else [0.0]
    dbg("clipper", "run.plan", probe_duration=duration, total_chunks=total_chunks, offsets=offsets)

    client = paid_deepgram_client()
    transcript: List[dict] = []
    detected_language: Optional[str] = None

    try:
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            print(
                json.dumps({"status": "transcribing_chunk", "chunk": idx, "total": total_chunks}),
                flush=True,
            )
            dbg("clipper", "deepgram.request", model="nova-3", diarize=True,
                chunk=idx, total=total_chunks, file=os.path.basename(chunk_path), language=detected_language)
            _t0 = time.monotonic()

            transcribe_kwargs = dict(
                model="nova-3",
                smart_format=True,
                punctuate=True,
                utterances=True,
                diarize=True,
                paragraphs=True,
            )
            if detected_language:
                transcribe_kwargs["language"] = detected_language

            with open(chunk_path, "rb") as f:
                audio_bytes = f.read()

            require_paid_asr()
            response = await client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                **transcribe_kwargs,
            )

            chunk_data = response.model_dump()
            chunk_entries = build_transcript_entries(chunk_data, offsets[idx - 1] + audio_offset)
            transcript.extend(chunk_entries)
            _utts = chunk_data.get("results", {}).get("utterances") or []
            dbg("clipper", "deepgram.response", chunk=idx,
                num_utterances=len(_utts), num_entries=len(chunk_entries),
                num_words=sum(len(e.get("words", [])) for e in chunk_entries),
                elapsed_s=round(time.monotonic() - _t0, 2))

            if not detected_language:
                channels = chunk_data.get("results", {}).get("channels", [])
                if channels:
                    detected_language = channels[0].get("detected_language")
    finally:
        if chunk_dir and os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir)

    duration = duration if duration > 0 else (transcript[-1]["end"] if transcript else 0)
    dbg("clipper", "run.done", num_entries=len(transcript),
        num_words=sum(len(e.get("words", [])) for e in transcript),
        duration=duration, language=detected_language or "en")

    print(
        json.dumps(
            {
                "status": "done",
                "transcript": transcript,
                "duration": duration,
                "fps": 0,
                "language": detected_language or "en",
                "model": "deepgram:nova-3",
            }
        ),
        flush=True,
    )


async def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: transcribe.py <audio_path> | transcribe.py --lavs <host_lav> <guest_lav>"}), flush=True)
        sys.exit(1)

    try:
        provider = transcription_provider()
    except LocalWhisperError as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)

    # Dual-lav mode: transcribe two individual mics (host=speaker 0, guest=speaker 1).
    if sys.argv[1] == "--lavs":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: transcribe.py --lavs <host_lav> <guest_lav>"}), flush=True)
            sys.exit(1)
        host_lav, guest_lav = sys.argv[2], sys.argv[3]
        dbg("clipper", "main.mode", mode="lavs", host_lav=host_lav, guest_lav=guest_lav)
        for p in (host_lav, guest_lav):
            if not os.path.exists(p):
                print(json.dumps({"error": f"File not found: {p}"}), flush=True)
                sys.exit(1)
            if not any(p.lower().endswith(ext) for ext in AUDIO_EXTENSIONS):
                print(json.dumps({"error": f"Lav inputs must be audio files: {p}"}), flush=True)
                sys.exit(1)
        if provider == DEEPGRAM_PROVIDER and not os.environ.get("DEEPGRAM_API_KEY"):
            print(json.dumps({"error": "DEEPGRAM_API_KEY not set"}), flush=True)
            sys.exit(1)
        try:
            await run_lav_transcription(host_lav, guest_lav)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
            sys.exit(1)
        return

    audio_path = sys.argv[1]
    dbg("clipper", "main.mode", mode="single-file", audio_path=audio_path)

    if not os.path.exists(audio_path):
        print(json.dumps({"error": f"File not found: {audio_path}"}), flush=True)
        sys.exit(1)

    is_video = any(audio_path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)
    is_audio = any(audio_path.lower().endswith(ext) for ext in AUDIO_EXTENSIONS)

    if not is_audio and not is_video:
        print(json.dumps({"error": "Unsupported file type. Please provide a video (mp4, mov) or audio file (mp3, wav, m4a, etc.)"}), flush=True)
        sys.exit(1)

    if provider == LOCAL_PROVIDER and not is_video:
        print(json.dumps({
            "error": "CLIPPER local-whisper requires two separate lav files or a truly isolated stereo video; mono/single-file audio needs Deepgram diarization",
        }), flush=True)
        sys.exit(1)

    if provider == DEEPGRAM_PROVIDER and not os.environ.get("DEEPGRAM_API_KEY"):
        print(json.dumps({"error": "DEEPGRAM_API_KEY not set"}), flush=True)
        sys.exit(1)

    extracted_audio_path: Optional[str] = None
    audio_offset = 0.0

    try:
        if is_video:
            # Capture audio stream start_time so we can shift Deepgram timestamps
            audio_start, _ = get_audio_metadata(audio_path)
            audio_offset = audio_start

            channels = get_channel_count(audio_path)
            print(json.dumps({"status": "channel_detected", "channels": channels}), flush=True)
            isolated = channels >= 2 and is_channel_isolated(audio_path)
            dbg("clipper", "main.channels", channels=channels, audio_offset=audio_offset,
                channel_isolated=isolated)
            if isolated:
                # Channel-isolated stereo: left = host (speaker 0), right = caller (speaker 1)
                await run_stereo_transcription(audio_path, audio_offset=audio_offset)
                return
            if provider == LOCAL_PROVIDER:
                raise LocalWhisperError(
                    "CLIPPER local-whisper cannot diarize mono/crosstalk camera audio; "
                    "select separate Host/Guest lavs or use a truly isolated stereo source"
                )
            # Mono OR cross-talk stereo -> fall through to mono extraction + diarization.
            # The mono ffmpeg call below uses -ac 1, which downmixes cross-talk stereo for us.

            # Mono video: fall through to standard extraction + diarization
            print(json.dumps({"status": "extracting_audio"}), flush=True)
            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="clipper-audio-")
            os.close(fd)
            result = subprocess.run(
                ["ffmpeg", "-i", audio_path, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "128k",
                 "-avoid_negative_ts", "make_zero", tmp, "-y"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(json.dumps({"error": f"ffmpeg audio extraction failed: {result.stderr.strip()}"}), flush=True)
                sys.exit(1)
            size_mb = round(os.path.getsize(tmp) / (1024 * 1024), 1)
            dbg("clipper", "main.extracted", tmp=tmp, size_mb=size_mb, audio_offset=audio_offset)
            print(json.dumps({"status": "audio_extracted", "size_mb": size_mb, "audio_offset": audio_offset}), flush=True)
            extracted_audio_path = tmp
            audio_path = tmp

        await run_transcription(audio_path, audio_offset=audio_offset)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)
    finally:
        if extracted_audio_path and os.path.exists(extracted_audio_path):
            os.unlink(extracted_audio_path)


if __name__ == "__main__":
    try:
        asyncio.run(run_asr_cli(main))
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)
