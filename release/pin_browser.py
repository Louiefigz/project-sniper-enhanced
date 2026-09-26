#!/usr/bin/env python3
"""Pin the rendering browser archive by SHA-256 (maintainer tool; needs network).

    python -m release.pin_browser [--keep-dir DIR]

Downloads the exact ``chrome-headless-shell`` build the shipped HyperFrames CLI
requires (``payload.chrome_version``) from Chrome for Testing, for both Mac
architectures and Windows x64, and records each archive's URL, size and SHA-256 in
``release/pins/chrome-headless-shell.json``. The build copies these into
``RELEASE.json`` and refuses a pin whose version differs from the one the
installed HyperFrames requires; the installer downloads the same URL and refuses
any archive whose SHA-256 differs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = Path(__file__).resolve().parent / "pins/chrome-headless-shell.json"
BASE_URL = "https://storage.googleapis.com/chrome-for-testing-public"
PLATFORMS = ("mac-arm64", "mac-x64", "win64")


def archive_url(version: str, platform: str) -> str:
    """The Chrome for Testing URL @puppeteer/browsers would download."""
    return f"{BASE_URL}/{version}/{platform}/chrome-headless-shell-{platform}.zip"


def _fetch(url: str, target: Path) -> dict[str, object]:
    """Download one archive and return its size and SHA-256."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as out:
        for block in iter(lambda: response.read(1 << 20), b""):
            digest.update(block)
            out.write(block)
    return {"url": url, "bytes": target.stat().st_size, "sha256": digest.hexdigest()}


def main(argv: list[str] | None = None) -> int:
    """Download both archives and write the pin file."""
    from release.payload import chrome_version  # noqa: PLC0415
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--keep-dir", type=Path, help="also keep the downloaded archives here")
    args = parser.parse_args(argv)
    version = chrome_version(ROOT)
    archives: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="sniper-pin-browser-") as tmp:
        for platform in PLATFORMS:
            target = Path(tmp) / f"chrome-headless-shell-{platform}.zip"
            archives[platform] = _fetch(archive_url(version, platform), target)
            if args.keep_dir:
                keep = args.keep_dir / version / platform
                keep.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, keep / target.name)
    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(json.dumps({"version": version, "archives": archives}, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"version": version, "archives": archives}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
