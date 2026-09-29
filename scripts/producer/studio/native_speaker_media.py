"""The two subprocess reads speaker observations make of the source, and the clock check between them (P2-06).

``probe_streams`` demuxes the source once with the pinned ffprobe and counts the first video stream's
packets. It decodes nothing. ``stream_clock`` then refuses a source whose frame index is not its time on
that clock:
- the counted video frames must match the video stream's duration x rate within one frame;
- the first audio stream must start within one frame of the first video stream.

Frame ``n`` is ``n / rate`` from the first video frame, and audio sample ``i`` is ``i / 8000`` from the
first audio sample. They share a clock only when both checks hold (REVIEW m2). The counted frames also
bound the decode-only keepalive frames (REVIEW M1).

``decode_audio`` decodes the first audio stream at 8000 Hz, in the source's own channel count, because
``audit.dialogue_consistency._window_rms`` designs its 120-3400 Hz band-pass at that rate. It never
forces two channels, so a mono source stays mono.
"""
from __future__ import annotations

import json
import math
from fractions import Fraction

import numpy as np

from audit.dialogue_consistency import SAMPLE_RATE
from cut_preview_io import MAX_JSON, run_bounded

PROBE_TIMEOUT_SECONDS = 900
AUDIO_TIMEOUT_SECONDS = 900
PROBE_ENTRIES = 'stream=index,codec_type,start_time,duration,nb_read_packets'


def probe_streams(path: str, ffprobe: str) -> dict:
    """Demux the source once (``-count_packets``) and return ffprobe's per-stream JSON.

    Args:
        path: The source media file.
        ffprobe: The pinned ffprobe.

    Returns:
        ffprobe's JSON, with ``streams[].nb_read_packets``, ``start_time`` and ``duration``.

    Raises:
        RuntimeError: ffprobe failed or wrote diagnostics.
    """
    command = [ffprobe, '-v', 'error', '-count_packets', '-show_entries', PROBE_ENTRIES, '-of', 'json', path]
    result = run_bounded(command, timeout=PROBE_TIMEOUT_SECONDS)
    if result.returncode or result.stderr.strip():
        raise RuntimeError('Speaker observation stream probe failed: ' + result.stderr[-3000:].decode(errors='replace'))
    return json.loads(result.stdout)


def _stream(probe: dict, kind: str) -> dict:
    """The first stream of one codec type (``0:v:0`` or ``0:a:0``)."""
    streams = [row for row in probe.get('streams', []) if isinstance(row, dict) and row.get('codec_type') == kind]
    if not streams:
        raise ValueError(f'The source has no {kind} stream; speaker observations need one')
    return streams[0]


def _seconds(stream: dict, key: str) -> Fraction:
    """A stream's decimal seconds field, exactly; 'N/A' or a missing field is refused by name."""
    value = stream.get(key)
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"The source's {stream.get('codec_type')} stream has no numeric {key} ({value!r})") from None


def stream_clock(probe: dict, rate: Fraction) -> dict:
    """Check that frame index is time x rate on one clock shared with the audio.

    Args:
        probe: ``probe_streams``' JSON.
        rate: The source frame rate (``source_clock``).

    Returns:
        ``{frameCount, videoDurationSeconds, videoStartSeconds, audioStartSeconds}``, recorded as
        ``sampling.clock``.

    Raises:
        ValueError: No counted frames, frames that do not match duration x rate within one frame, or
            audio that starts more than one frame away from the video.
    """
    video, audio = _stream(probe, 'video'), _stream(probe, 'audio')
    count = video.get('nb_read_packets')
    if type(count) is not str or not count.isdigit() or int(count) <= 0:
        raise ValueError(f"The source's video stream has no counted frames ({count!r})")
    frames, duration = int(count), _seconds(video, 'duration')
    start, audio_start = _seconds(video, 'start_time'), _seconds(audio, 'start_time')
    if abs(frames - duration * rate) > 1:
        raise ValueError(f'Speaker observations need frame index = time x rate: the video stream holds {frames} '
                         f'frames over {float(duration)} s, not {float(duration * rate):.2f} at {rate} fps')
    if abs(audio_start - start) * rate > 1:
        raise ValueError(f'The audio stream starts {float(audio_start - start):+.6f} s from the video stream, more '
                         'than one frame, so source frames and audio samples do not share a clock')
    return {'frameCount': frames, 'videoDurationSeconds': float(duration), 'videoStartSeconds': float(start),
            'audioStartSeconds': float(audio_start)}


def decode_audio(source: dict, ffmpeg: str) -> np.ndarray:
    """Decode the source's first audio stream once, at 8000 Hz, in its own channel count (1 or 2).

    Args:
        source: The manifest source row (``path``, ``duration``, ``audio.channels``).
        ffmpeg: The pinned ffmpeg.

    Returns:
        Float64 samples shaped (count, channels).

    Raises:
        ValueError: The source has no audio or more than two channels.
        RuntimeError: The decode failed or returned a partial sample frame.
    """
    audio = source.get('audio') or {}
    channels = audio.get('channels')
    if audio.get('present') is not True or type(channels) is not int or channels not in (1, 2):
        raise ValueError(f'Speaker observations measure mono or stereo audio; the source has {channels!r} channel(s)')
    command = [ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', source['path'], '-map', '0:a:0', '-vn',
               '-ac', str(channels), '-ar', str(SAMPLE_RATE), '-f', 'f32le', 'pipe:1']
    maximum = (math.ceil(source['duration']) + 2) * SAMPLE_RATE * channels * 4 + MAX_JSON
    result = run_bounded(command, maximum=maximum, timeout=AUDIO_TIMEOUT_SECONDS)
    if result.returncode or result.stderr.strip() or not result.stdout:
        raise RuntimeError('Speaker observation audio decode failed: ' + result.stderr[-3000:].decode(errors='replace'))
    raw = np.frombuffer(result.stdout, dtype='<f4')
    if raw.size % channels:
        raise RuntimeError('Speaker observation audio decode returned a partial sample frame')
    return raw.reshape(-1, channels).astype(np.float64)
