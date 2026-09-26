"""Assemble an unpacked native-Intel macOS qualification package."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from release import payload, pins, runtime_tools
from release.stage import StageReport, stage_tree

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = "osx-64"


def _copy_ffmpeg(destination: Path) -> None:
    """Copy the exact pinned Intel FFmpeg artifact into the buyer package."""
    target = runtime_tools.runtime_target(PLATFORM)
    pin = json.loads(target.ffmpeg_pin.read_text(encoding="utf-8"))
    artifact = pin["artifact"]
    source = runtime_tools.DIST / artifact["file"]
    installed = destination / "install" / "deps" / artifact["file"]
    installed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, installed)


def assemble(destination: Path) -> None:
    """Create the exact Intel-visible package surface at ``destination``."""
    if destination.exists():
        raise RuntimeError(f"qualification destination already exists: {destination}")
    destination.mkdir(parents=True)
    stage_tree(ROOT, destination, StageReport())
    shutil.copytree(payload.PAYLOAD, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    intel = runtime_tools.check(PLATFORM)
    _copy_ffmpeg(destination)
    chrome = json.loads(pins.BROWSER_PIN.read_text(encoding="utf-8"))["version"]
    components = {
        "app_version": json.loads((ROOT / "package.json").read_text())["version"],
        "chrome_headless_shell": chrome,
        "chrome_headless_shell_sha256": pins.browser_hashes(chrome),
        "chrome_headless_shell_bytes": pins.browser_sizes(chrome),
        "node_floor": "22.13.0",
        "node_floor_set_by": ["qualification mirror of release node floor"],
        **intel,
        "runtime_targets": {PLATFORM: intel},
        "supported_platform": f"macOS {intel['runtime_min_macos']}+ on Intel",
    }
    release = {
        "product": "Project Sniper",
        "version": "macos-intel-qualification",
        "components": components,
        "sellable": False,
        "note": "Ephemeral native-Intel qualification package; not a release archive.",
    }
    (destination / "RELEASE.json").write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Parse the destination and assemble the qualification package."""
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    assemble(args.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
