"""Shared generated media and helpers for the native admission jail tests."""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
HAVE_NATIVE = sys.platform == "darwin" and Path(FFMPEG).is_file() and Path("/usr/bin/sandbox-exec").exists()
FONT = Path(__file__).resolve().parents[3] / "assets" / "fonts" / "Inter-Regular.ttf"


def ffmpeg(*args: str) -> None:
    """Generate test media with the host ffmpeg (trusted generation, not admission)."""
    subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", *args], stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=60, check=True)


def valid_mp4(path: Path, size: str = "320x180", seconds: int = 2) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    return path


class DecoyListener:
    """A loopback TCP listener that records whether anything connected to it."""

    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(4)
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.connections = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except OSError:
                continue
            self.connections += 1
            connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.socket.close()
