"""Platform metadata shared by Sniper's release builders.

The buyer launchers do their tiny pre-Python platform detection themselves. This
module is the maintainer-side source of truth for runtime lock, measurement and
FFmpeg build paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUPPORTED = ("osx-arm64", "osx-64", "win-64")


@dataclass(frozen=True)
class RuntimeTarget:
    """Files and installer tokens belonging to one native runtime target."""

    platform: str
    browser_platform: str
    lock: Path
    lock_json: Path
    ffmpeg_pin: Path
    measured: Path

    @property
    def is_macos(self) -> bool:
        """Whether this target uses the macOS native admission runtime."""
        return self.platform.startswith("osx-")


def target(platform: str) -> RuntimeTarget:
    """Return the validated release paths for ``platform``."""
    if platform not in SUPPORTED:
        raise ValueError(f"unsupported runtime platform: {platform}")
    browser = {"osx-arm64": "mac-arm64", "osx-64": "mac-x64", "win-64": "win64"}[platform]
    deps = ROOT / "payload_files/install/deps"
    suffix = "" if platform == "osx-arm64" else f"-{platform}"
    pin = ROOT / "runtime_deps" / f"sniper-ffmpeg{suffix}.json"
    measured = ROOT / "runtime_deps" / f"measured-min-{platform}.json"
    if platform == "osx-arm64":
        measured = ROOT / "runtime_deps/measured-min-macos.json"
    lock = deps / f"{platform}.lock"
    return RuntimeTarget(platform, browser, lock, lock.with_suffix(".json"), pin, measured)
