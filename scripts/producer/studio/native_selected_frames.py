"""One-pass bounded RGB verification using the shared owned-process reader."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from cut_preview_io import MAX_JSON, file_identity, read_bytes, real_directory, run_bounded
from edit.exact_timing import PositiveRational

COLOR_FILTER = 'zscale=p=1:t=13:m=0:r=full:agamma=0,format=gbrpf32le,format=rgb24'
MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_SELECTED_FRAMES = 100000


@dataclass(frozen=True)
class SelectedFrames:
    """Exact frame indexes and output geometry; never infer time from rounded FPS."""

    frames: tuple[int, ...]
    width: int
    height: int
    total_frames: int

    def __post_init__(self) -> None:
        """Reject ambiguous schedules before launching a decoder or allocating RGB."""
        dimensions = (self.width, self.height, self.total_frames)
        if any(type(value) is not int or value <= 0 for value in dimensions):
            raise ValueError('Selected-frame canvas/count must be positive integers')
        if self.frame_bytes > MAX_FRAME_BYTES:
            raise ValueError('Selected-frame geometry exceeds the bounded frame buffer')
        if not 0 < len(self.frames) <= MAX_SELECTED_FRAMES:
            raise ValueError('Selected-frame inventory is empty or exceeds its bound')
        if any(type(value) is not int or not 0 <= value < self.total_frames for value in self.frames):
            raise ValueError('Selected frame is outside the exact output frame clock')
        if list(self.frames) != sorted(set(self.frames)):
            raise ValueError('Selected-frame schedule must be ordered and unique')

    @property
    def frame_bytes(self) -> int:
        """Exact byte count for one unscaled RGB24 picture."""
        return self.width * self.height * 3

    @property
    def shape(self) -> tuple[int, int, int]:
        """NumPy uses height before width."""
        return self.height, self.width, 3

    @property
    def filter_bytes(self) -> bytes:
        """Keep the original selection expression outside the operating-system argv limit."""
        select = selection_expression(self.frames)
        return f"select='{select}',{COLOR_FILTER}".encode('ascii')


def selection_expression(frames: tuple[int, ...]) -> str:
    """Merge runs and balance sums so long schedules do not exhaust FFmpeg's parser stack."""
    terms = []
    start = previous = frames[0]
    for frame in (*frames[1:], None):
        if frame == previous + 1:
            previous = frame
            continue
        terms.append(f'eq(n,{start})' if start == previous else f'between(n,{start},{previous})')
        start = previous = frame
    while len(terms) > 1:
        terms = [f'({terms[index]}+{terms[index + 1]})' if index + 1 < len(terms) else terms[index]
                 for index in range(0, len(terms), 2)]
    return terms[0]


def selected_frames(canvas: dict, rows: list[dict]) -> SelectedFrames:
    """Keep legacy portrait defaults while admitting explicit output dimensions."""
    numerator, denominator = map(int, canvas['frameRate'].split('/'))
    PositiveRational(numerator, denominator)
    if ('width' in canvas) != ('height' in canvas):
        raise ValueError('Selected-frame canvas requires both explicit dimensions')
    return SelectedFrames(tuple(row['frame'] for row in rows),
                          canvas.get('width', 1080), canvas.get('height', 1920),
                          canvas['totalFrames'])


@dataclass
class FrameConsumer:
    """Keep at most one RGB frame plus one bounded pipe read, in original order."""

    selection: SelectedFrames
    compare: Callable[[int, np.ndarray], dict]
    pending: bytearray = field(default_factory=bytearray)
    comparisons: list[dict] = field(default_factory=list)
    hasher: Any = field(default_factory=hashlib.sha256)
    received: int = 0
    peak_buffer_bytes: int = 0

    def consume(self, data: bytes) -> None:
        """Hash the same concatenated RGB bytes that the old scratch file held."""
        self.received += len(data)
        if self.received > len(self.selection.frames) * self.selection.frame_bytes:
            raise RuntimeError('Selected RGB decode returned excess frames or dimensions')
        self.hasher.update(data)
        for offset in range(0, len(data), 65536):
            self.pending.extend(data[offset:offset + 65536])
            self.peak_buffer_bytes = max(self.peak_buffer_bytes, len(self.pending))
            while len(self.pending) >= self.selection.frame_bytes:
                self._compare_next()

    def _compare_next(self) -> None:
        """Release the array view before resizing the bounded byte buffer."""
        frame = self.selection.frames[len(self.comparisons)]
        pixels = np.frombuffer(self.pending, dtype=np.uint8,
                               count=self.selection.frame_bytes).reshape(self.selection.shape)
        try:
            self.comparisons.append(self.compare(frame, pixels))
        finally:
            del pixels
        del self.pending[:self.selection.frame_bytes]

    def finish(self) -> dict:
        """An early EOF cannot qualify a partial comparison inventory."""
        if self.pending or len(self.comparisons) != len(self.selection.frames):
            raise RuntimeError('Selected RGB decode returned an incomplete frame inventory')
        return {'format': 'rgb24', 'frames': len(self.comparisons),
                'sha256': self.hasher.hexdigest(), 'mode': 'streamed-one-pass',
                'decodedBytes': self.received, 'scratchBytes': 0,
                'peakRgbBufferBytes': self.peak_buffer_bytes,
                'frameBytes': self.selection.frame_bytes}


def require_encoded_geometry(candidate: Path, selection: SelectedFrames) -> None:
    """Reject even equal-area dimension mismatches before interpreting raw pixels."""
    result = run_bounded(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                          '-show_entries', 'stream=width,height', '-of', 'json', str(candidate)])
    if result.returncode or result.stderr:
        raise RuntimeError('Selected RGB geometry probe failed')
    streams = json.loads(result.stdout)['streams']
    expected = {'width': selection.width, 'height': selection.height}
    if len(streams) != 1 or {key: streams[0].get(key) for key in expected} != expected:
        raise RuntimeError('Encoded picture dimensions differ from the strategy canvas')


@contextmanager
def owned_filter(directory: Path, content: bytes) -> Iterator[Path]:
    """Create one exclusive script and clean only that inode, including on cancellation."""
    real_directory(directory)
    path = directory / 'selected-filter.txt'
    handle = path.open('xb')
    identity = file_identity(path.lstat())
    try:
        with handle:
            handle.write(content)
        identity = file_identity(path.lstat())
        yield path
        if file_identity(path.lstat()) != identity or read_bytes(path, len(content)) != content:
            raise RuntimeError('Selected-frame filter changed during verification')
    finally:
        handle.close()
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if current is not None and (current.st_dev, current.st_ino) == identity[:2]:
            path.unlink()


def compare_selected_frames(candidate: Path, selection: SelectedFrames,
                            compare: Callable[[int, np.ndarray], dict],
                            directory: Path) -> tuple[list[dict], dict]:
    """Decode the unchanged integer-index schedule once, without RGB disk files."""
    require_encoded_geometry(candidate, selection)
    content = selection.filter_bytes
    command = ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(candidate),
               '-map', '0:v:0', '-an', '-filter_script:v', str(directory / 'selected-filter.txt'),
               '-fps_mode', 'passthrough', '-threads', '1', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', 'pipe:1']
    consumer = FrameConsumer(selection, compare)
    maximum = len(selection.frames) * selection.frame_bytes + MAX_JSON
    with owned_filter(directory, content):
        timeout = max(180, min(1800, selection.total_frames / 15))
        result = run_bounded(command, maximum=maximum, timeout=timeout, consume_stdout=consumer.consume)
    if result.returncode or result.stderr:
        raise RuntimeError('Selected RGB decode failed: ' + result.stderr[:4096].decode(errors='replace'))
    return consumer.comparisons, {**consumer.finish(), 'filterScriptBytes': len(content),
                                 'scratchBytes': len(content), 'rgbScratchBytes': 0}
