"""How speaker observations read the source: probes, the frame clock, the decode schedule and the audio (P2-06).

``probe_streams`` makes three ffprobe reads:
- the stream headers;
- the first video stream's packet timestamps (a demux; nothing decoded);
- the first decoded audio frame's timestamp (the first few audio packets are decoded).

``stream_clock`` turns them into the packet ``FrameClock`` (X78 DM1):
- frame ``n`` is the ``n``-th smallest presentation timestamp among packets not flagged discard;
- frame times are measured from the first decoded audio frame, which is the transcript's second 0.

The first decoded frame's timestamp already accounts for encoder priming the decoder drops, so 60p
sources stay within a frame (X87 F-m1). The audio header's ``start_time`` is recorded as information
only.

The mapping is exact, with no threshold. Drift from the nominal rate is recorded in ``sampling.clock`` for
information only. A source is refused only when a timestamp, a ``time_base`` or a ``start_time`` cannot
be read. A container without stream durations (MKV/WebM) works through its packets.

``frame_selection`` adds decode-only keepalive frames to the sampled frames. With them, no stretch of the
one decode, from frame 0 to the last frame, passes ``KEEPALIVE_FRAMES`` frames without a selected frame.
Each prints progress for the idle watchdog and is never measured (REVIEW M1).

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
from studio.native_selected_frames import SelectedFrames
from studio.native_speaker_sampling import FrameClock

PROBE_TIMEOUT_SECONDS = 900
AUDIO_TIMEOUT_SECONDS = 900
KEEPALIVE_FRAMES = 1800   # 60 s of 30p source: the 600 s idle deadline then holds down to a 3 fps decode
HEADER_ENTRIES = 'stream=index,codec_type,start_time,time_base'
PACKET_ENTRIES = 'packet=pts,flags'
FIRST_AUDIO_PACKETS = '%+#8'   # decode at most 8 audio packets: priming the decoder drops can span two


def _read(command: list[str]) -> bytes:
    """Run one bounded ffprobe; its stdout, or a named refusal."""
    result = run_bounded(command, timeout=PROBE_TIMEOUT_SECONDS)
    if result.returncode or result.stderr.strip():
        raise RuntimeError('Speaker observation stream probe failed: ' + result.stderr[-3000:].decode(errors='replace'))
    return result.stdout


def probe_streams(path: str, ffprobe: str) -> dict:
    """Stream headers, the first video stream's packet timestamps, and the first decoded audio frame's pts.

    Args:
        path: The source media file.
        ffprobe: The pinned ffprobe.

    Returns:
        ``{streams: [{codec_type, start_time, time_base, ...}], packets: [(pts, flags), ...] in demux order,
        audioFirstPts: the first decoded audio frame's pts in the audio time_base, or '' if none decoded}``.

    Raises:
        RuntimeError: ffprobe failed or wrote diagnostics.
    """
    header = _read([ffprobe, '-v', 'error', '-show_entries', HEADER_ENTRIES, '-of', 'json', path])
    packets = _read([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', PACKET_ENTRIES,
                     '-of', 'csv=p=0', path])
    first = _read([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-read_intervals', FIRST_AUDIO_PACKETS,
                   '-show_entries', 'frame=pts', '-of', 'csv=p=0', path])
    rows = [line.partition(',') for line in packets.decode(errors='replace').splitlines() if line.strip()]
    frames = [line.split(',')[0].strip() for line in first.decode(errors='replace').splitlines() if line.strip()]
    return {'streams': json.loads(header).get('streams', []), 'packets': [(pts, flags) for pts, _, flags in rows],
            'audioFirstPts': frames[0] if frames else ''}


def _stream(probe: dict, kind: str) -> dict:
    """The first stream of one codec type (``0:v:0`` or ``0:a:0``)."""
    streams = [row for row in probe.get('streams', []) if isinstance(row, dict) and row.get('codec_type') == kind]
    if not streams:
        raise ValueError(f'The source has no {kind} stream; speaker observations need one')
    return streams[0]


def _exact(stream: dict, key: str) -> Fraction:
    """A stream's ``start_time`` or ``time_base``, exactly; an unreadable value is refused by name."""
    value = stream.get(key)
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"The source's {stream.get('codec_type')} stream has no readable {key} ({value!r})") from None


def _pts(text: str, what: str = 'A video packet') -> int:
    """An integer presentation timestamp; 'N/A' or nothing is refused by name."""
    if not text.strip().lstrip('-').isdigit():
        raise ValueError(f'{what} has no readable presentation timestamp ({text!r})')
    return int(text)


def stream_clock(probe: dict, rate: Fraction) -> tuple[FrameClock, dict]:
    """The packet frame clock on the transcript's clock, and what it records about drift.

    Args:
        probe: ``probe_streams``' result.
        rate: The nominal frame rate (``source_clock``).

    Returns:
        (the packet ``FrameClock``, ``sampling.clock``: ``frameCount``, ``nominalRate``, ``timeBase``,
        ``videoStartSeconds``, ``audioStartSeconds`` (the first decoded audio frame, the alignment),
        ``audioStreamStartSeconds`` (the header, information), ``firstFrameSeconds``, ``lastFrameSeconds``,
        ``indexDriftFrames``, ``discardedPackets``). Drift is information only.

    Raises:
        ValueError: A missing stream, an unreadable time_base, start_time or timestamp, or no kept packet.
    """
    video, audio = _stream(probe, 'video'), _stream(probe, 'audio')
    base, stream_start = _exact(video, 'time_base'), _exact(audio, 'start_time')
    audio_start = _pts(probe.get('audioFirstPts', ''), 'The first decoded audio frame') * _exact(audio, 'time_base')
    kept = [pts for pts, flags in probe.get('packets', []) if 'D' not in flags]
    times = tuple(sorted(_pts(pts) * base - audio_start for pts in kept))
    if not times:
        raise ValueError("The source's video stream has no presentable packets")
    span = (times[-1] - times[0]) * rate
    info = {'frameCount': len(times), 'nominalRate': f'{rate.numerator}/{rate.denominator}', 'timeBase': str(base),
            'videoStartSeconds': round(float(_exact(video, 'start_time')), 6),
            'audioStartSeconds': round(float(audio_start), 6), 'audioStreamStartSeconds': round(float(stream_start), 6),
            'firstFrameSeconds': round(float(times[0]), 6),
            'lastFrameSeconds': round(float(times[-1]), 6), 'indexDriftFrames': round(float(len(times) - 1 - span), 3),
            'discardedPackets': len(probe.get('packets', [])) - len(kept)}
    return FrameClock(rate, times), info


def keepalive_frames(planned: list[int], frame_count: int) -> list[int]:
    """Decode-only frames that keep every stretch of the one decode within KEEPALIVE_FRAMES frames.

    Args:
        planned: The sampled frames, ascending.
        frame_count: Frames in the video stream (its presentable packets).

    Returns:
        Frames not in ``planned``: every KEEPALIVE_FRAMES-th frame from 0, and the last frame. With them the
        selection starts at frame 0, ends at the last frame, and no two neighbours are further apart.
    """
    grid = {*range(0, frame_count, KEEPALIVE_FRAMES), frame_count - 1}
    return sorted(grid - set(planned))


def frame_selection(source: dict, sampling: dict, frame_count: int) -> SelectedFrames:
    """The sampled frames plus their keepalives, as one exact selection over the video's frames.

    Args:
        source: The manifest source row (its ``resolution`` is the decoded geometry).
        sampling: The packet-clock ``frame_plan``.
        frame_count: Frames in the video stream (``sampling.clock.frameCount``).

    Returns:
        The shared reader's ``SelectedFrames``.

    Raises:
        ValueError: A sampled frame lies at or past the stream's last frame.
    """
    planned = [row['frame'] for row in sampling['frames']]
    if type(frame_count) is not int or frame_count <= 0 or (planned and planned[-1] >= frame_count):
        raise ValueError(f'Speaker observation sampling reaches source frame {planned[-1] if planned else None}, '
                         f'but the video stream holds {frame_count!r} frames')
    width, height = source['resolution']
    return SelectedFrames(tuple(sorted({*planned, *keepalive_frames(planned, frame_count)})), width, height,
                          frame_count)


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
