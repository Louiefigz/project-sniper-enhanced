"""Assemble an unpacked Windows qualification package without Mac-only artifacts.

This is not the release builder. It creates the exact Windows-visible package
surface for a clean Windows runner, where the real installer downloads and
verifies the win-64 lock. The release builder still owns distributable archives.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from release import payload, pins, runtime_tools
from release.stage import StageReport, stage_tree

ROOT = Path(__file__).resolve().parents[1]


def assemble(destination: Path) -> None:
    """Create the unpacked Windows qualification package at ``destination``."""
    if destination.exists():
        raise RuntimeError(f"qualification destination already exists: {destination}")
    destination.mkdir(parents=True)
    stage_tree(ROOT, destination, StageReport())
    shutil.copytree(payload.PAYLOAD, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    chrome = json.loads(pins.BROWSER_PIN.read_text(encoding="utf-8"))["version"]
    # The distributable build derives this from both lockfiles through semver.
    # Qualification runs before npm exists, so it uses the last derived value;
    # release.build_package remains the authority and refuses drift.
    node = {"floor": "22.13.0", "set_by": ["qualification mirror of release node floor"]}
    windows = runtime_tools.check("win-64")
    components = {
        "app_version": json.loads((ROOT / "package.json").read_text())["version"],
        "chrome_headless_shell": chrome,
        "chrome_headless_shell_sha256": pins.browser_hashes(chrome),
        "chrome_headless_shell_bytes": pins.browser_sizes(chrome),
        "node_floor": node["floor"], "node_floor_set_by": node["set_by"],
        **windows, "runtime_targets": {"win-64": windows},
        "supported_platform": f"Windows {windows['runtime_min_windows']}+ on x64",
    }
    release = {"product": "Project Sniper", "version": "windows-qualification",
               "components": components, "sellable": False,
               "note": "Ephemeral Windows qualification package; not a release archive."}
    (destination / "RELEASE.json").write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    assemble(args.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
