"""Bound long native jobs by frames while retaining a separate progress watchdog."""
from __future__ import annotations

import math
import re
from fractions import Fraction
from pathlib import Path


def workload_budget(canvas: dict) -> dict:
    """Plan conservative time, never an ETA or permission to weaken resource gates."""
    frames = canvas['totalFrames']
    rate = Fraction(canvas['frameRate'])
    if type(frames) is not int or frames <= 0 or not 1 <= rate <= 60:
        raise ValueError('Workload requires positive integer frames and 1–60 fps')
    seconds = frames / rate
    if seconds > 900:
        raise ValueError('Native long export currently admits up to 15 minutes')
    # The measured Trevor capture was 12.7 fps. Four fps leaves headroom;
    # independent resource and no-progress limits still terminate stalled jobs.
    picture = math.ceil(frames / 4) + 600
    return {'pictureSeconds': picture, 'ownerSeconds': picture + 600,
            'sampleSeconds': max(1200, math.ceil(picture / 2) + 600),
            'verificationSeconds': max(600, math.ceil(seconds * 2)),
            'idleSeconds': 600, 'planningCaptureFps': 4,
            'frames': frames, 'durationSeconds': float(seconds)}


class ProgressWatch:
    """Read bounded incremental logs; duplicate warnings are not forward progress."""

    def __init__(self, path: Path, started: float, idle: float) -> None:
        """Start only at child launch, not while acquiring host capacity."""
        self.path, self.last_progress, self.idle = path, started, idle
        self.offset, self.pending, self.highest = 0, b'', {}

    def inspect(self, now: float) -> bool:
        """Return false on a stalled child, truncation or unbounded log backlog."""
        size = self.path.stat().st_size
        if size < self.offset or size - self.offset > 8 * 1024 * 1024:
            raise RuntimeError('Native progress log truncated or exceeded its read bound')
        with self.path.open('rb') as handle:
            handle.seek(self.offset)
            data = handle.read(8 * 1024 * 1024)
        self.offset += len(data)
        lines = (self.pending + data).replace(b'\r', b'\n').split(b'\n')
        self.pending = lines.pop()
        if len(self.pending) > 65536:
            raise RuntimeError('Native progress line exceeds its bound')
        for line in lines:
            if self.advance(line.decode('utf-8', errors='replace')):
                self.last_progress = now
        return now - self.last_progress <= self.idle

    def advance(self, line: str) -> bool:
        """Accept advancing SDK frame counts or adapter phase-local counters only."""
        match = re.search(r'(Streaming frame|Extracting frames from video) (\d+)/(\d+)', line)
        if match:
            key, value = (match[1], int(match[3])), int(match[2])
        else:
            match = re.fullmatch(r'SNIPER_PROGRESS ([a-z-]+) (\d+)', line.strip())
            if not match:
                return False
            key, value = match[1], int(match[2])
        if value <= self.highest.get(key, -1):
            return False
        self.highest[key] = value
        return True
