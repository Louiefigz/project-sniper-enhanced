#!/usr/bin/env python3
"""Transcribe media with Deepgram (default) or local whisper.cpp."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from deepgram import AsyncDeepgramClient
from local_whisper import (LOCAL_PROVIDER, LocalTranscribeRequest,
                           LocalWhisperError, transcribe_media,
                           transcription_provider)

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
    start_time = 0.0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            val = stream.get("start_time")
            if val and val != "N/A":
                start_time = float(val)
            break
    return (start_time, duration)


def split_audio_if_needed(audio_path: str) -> tuple[List[str], Optional[str]]:
    size = os.path.getsize(audio_path)
    dbg("transcribe", "split.check", audio_path=audio_path,
        size_mb=round(size / (1024 * 1024), 2), limit_mb=round(MAX_DEEPGRAM_FILE_SIZE / (1024 * 1024), 1))
    if size <= MAX_DEEPGRAM_FILE_SIZE:
        return [audio_path], None

    print(json.dumps({"status": "chunking_audio"}), flush=True)
    temp_dir = tempfile.mkdtemp(prefix="clipper-chunks-")
    pattern = os.path.join(temp_dir, FRAGMENT_TEMPLATE)
    result = subprocess.run(
        [
            "ffmpeg", "-i", audio_path,
            "-f", "segment",
            "-segment_time", str(CHUNK_DURATION_SECONDS),
            "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "16000", "-ac", "1",
            pattern, "-y",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg chunking failed (exit {result.returncode}): {result.stderr.strip()[-500:]}"
        )

    chunks = sorted(Path(temp_dir).glob("chunk-*.mp3"))
    if not chunks:
        raise RuntimeError("Chunking produced no files")

    chunk_paths = [str(c) for c in chunks]
    dbg("transcribe", "split.chunks", count=len(chunk_paths),
        sizes_mb=[round(os.path.getsize(p) / (1024 * 1024), 2) for p in chunk_paths])
    oversized = [(p, os.path.getsize(p)) for p in chunk_paths if os.path.getsize(p) > MAX_DEEPGRAM_FILE_SIZE]
    if oversized:
        biggest = max(oversized, key=lambda t: t[1])
        raise RuntimeError(
            f"Chunking produced an oversized chunk: {os.path.basename(biggest[0])} = "
            f"{biggest[1]:,} bytes (limit {MAX_DEEPGRAM_FILE_SIZE:,}). "
            f"Source size was {size:,} bytes; chunks produced: {len(chunk_paths)}."
        )

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
                    }
                    for word in raw_words
                ],
            }
        )
    return entries


async def run_transcription(audio_path: str, audio_offset: float = 0.0) -> None:
    """Single async entry point — all Deepgram calls happen here."""
    dbg("transcribe", "run.enter", audio_path=audio_path, audio_offset=audio_offset)
    _, duration = get_audio_metadata(audio_path)
    chunk_paths, chunk_dir = split_audio_if_needed(audio_path)
    total_chunks = len(chunk_paths)
    offsets = get_chunk_offsets(audio_path, total_chunks) if total_chunks > 1 else [0.0]
    dbg("transcribe", "run.plan", probe_duration=duration, total_chunks=total_chunks, offsets=offsets)

    client = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
    transcript: List[dict] = []
    detected_language: Optional[str] = None

    try:
        for idx, chunk_path in enumerate(chunk_paths, start=1):
            print(
                json.dumps({"status": "transcribing_chunk", "chunk": idx, "total": total_chunks}),
                flush=True,
            )
            dbg("transcribe", "deepgram.request", model="nova-3",
                chunk=idx, total=total_chunks, file=os.path.basename(chunk_path), language=detected_language)
            _t0 = time.monotonic()

            transcribe_kwargs = dict(
                model="nova-3",
                smart_format=True,
                punctuate=True,
                utterances=True,
                paragraphs=True,
            )
            if detected_language:
                transcribe_kwargs["language"] = detected_language

            with open(chunk_path, "rb") as f:
                audio_bytes = f.read()

            response = await client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                **transcribe_kwargs,
            )

            chunk_data = response.model_dump()
            chunk_entries = build_transcript_entries(chunk_data, offsets[idx - 1] + audio_offset)
            transcript.extend(chunk_entries)
            _utts = chunk_data.get("results", {}).get("utterances") or []
            dbg("transcribe", "deepgram.response", chunk=idx,
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
    dbg("transcribe", "run.done", num_entries=len(transcript),
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


def run_local_transcription(media_path: str) -> None:
    """Run the no-network whisper.cpp lane and preserve the worker NDJSON shape."""
    dbg("transcribe", "local.enter", media_path=media_path)
    result = transcribe_media(
        LocalTranscribeRequest(path=media_path),
        emit=lambda event: print(json.dumps(event), flush=True),
    )
    dbg("transcribe", "local.done", model=result["model"],
        utterances=len(result["transcript"]))
    print(json.dumps(result), flush=True)


async def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: transcribe.py <audio_path>"}), flush=True)
        sys.exit(1)

    audio_path = sys.argv[1]

    if not os.path.exists(audio_path):
        print(json.dumps({"error": f"File not found: {audio_path}"}), flush=True)
        sys.exit(1)

    is_video = any(audio_path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)
    is_audio = any(audio_path.lower().endswith(ext) for ext in AUDIO_EXTENSIONS)
    dbg("transcribe", "main.input", audio_path=audio_path, is_video=is_video, is_audio=is_audio)

    if not is_audio and not is_video:
        print(json.dumps({"error": "Unsupported file type. Please provide a video (mp4, mov) or audio file (mp3, wav, m4a, etc.)"}), flush=True)
        sys.exit(1)

    try:
        provider = transcription_provider()
    except LocalWhisperError as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)

    if provider == LOCAL_PROVIDER:
        try:
            run_local_transcription(audio_path)
        except (LocalWhisperError, OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
            sys.exit(1)
        return

    if not os.environ.get("DEEPGRAM_API_KEY"):
        print(json.dumps({"error": "DEEPGRAM_API_KEY not set"}), flush=True)
        sys.exit(1)

    extracted_audio_path: Optional[str] = None
    audio_offset = 0.0

    try:
        source_size = os.path.getsize(audio_path)
        needs_normalize = is_video or source_size > MAX_DEEPGRAM_FILE_SIZE
        dbg("transcribe", "main.normalize", source_size_mb=round(source_size / (1024 * 1024), 2),
            needs_normalize=needs_normalize)

        if needs_normalize:
            audio_start, _ = get_audio_metadata(audio_path)
            audio_offset = audio_start

            print(json.dumps({"status": "extracting_audio"}), flush=True)
            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="clipper-audio-")
            os.close(fd)
            ffmpeg_cmd = ["ffmpeg", "-i", audio_path]
            if is_video:
                ffmpeg_cmd.append("-vn")
            ffmpeg_cmd += [
                "-c:a", "libmp3lame",
                "-ar", "16000", "-ac", "1", "-b:a", "128k",
                "-avoid_negative_ts", "make_zero",
                tmp, "-y",
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(json.dumps({"error": f"ffmpeg audio extraction failed: {result.stderr.strip()[-500:]}"}), flush=True)
                sys.exit(1)
            size_mb = round(os.path.getsize(tmp) / (1024 * 1024), 1)
            dbg("transcribe", "main.extracted", tmp=tmp, size_mb=size_mb, audio_offset=audio_offset)
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
    asyncio.run(main())
