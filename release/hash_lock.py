#!/usr/bin/env python3
"""Regenerate the installer's hash-pinned Python lock (maintainer tool; needs network).

    python -m release.hash_lock [--check]

Reads the pinned ``name==version`` set from
``release/payload_files/install/requirements.lock.txt`` and, for every supported
interpreter (CPython 3.12, 3.13, 3.14) and every macOS platform tag a buyer's pip
may choose between (arm64 on macOS 13, 14 and 26, where numpy/scipy switch wheel
builds; x86_64 on macOS 14 and 26, untested), runs::

    pip download --only-binary=:all: --no-deps --platform <tag> --python-version <v> ...

then hashes every downloaded file. The lock is rewritten with one
``--hash=sha256:`` per distinct file, so ``pip install --require-hashes
--only-binary=:all:`` resolves on every combination above and refuses anything
else. A package without a wheel for a combination fails this tool (no sdist is
ever hashed or built on a buyer's Mac). ``--check`` downloads and compares
without writing, exiting 1 when the lock is stale.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

LOCK = Path(__file__).resolve().parent / "payload_files/install/requirements.lock.txt"
PYTHONS = ("3.12", "3.13", "3.14")
# opencv-python-headless 4.14.0.94 publishes macOS wheels for arm64 on 13+ and for
# x86_64 on 14+ only, so an Intel Mac on macOS 13 has no installable set.
PLATFORMS = ("macosx_13_0_arm64", "macosx_14_0_arm64", "macosx_26_0_arm64",
             "macosx_14_0_x86_64", "macosx_26_0_x86_64")


def pins(lock: Path) -> list[tuple[str, str]]:
    """``(name, version)`` for every requirement line of a plain or hashed lock."""
    found = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        text = line.strip().rstrip("\\").strip()
        if text and not text.startswith(("#", "--")) and "==" in text:
            name, version = text.split("==", 1)
            found.append((name.strip(), version.split()[0]))
    return found


def _download(requirements: Path, python: str, platform: str, dest: Path) -> None:
    """Fetch the wheel pip would choose for one interpreter/platform combination."""
    argv = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "-q",
            "--only-binary=:all:", "--no-deps", "--implementation", "cp", "--python-version", python,
            "--platform", platform, "-r", str(requirements), "-d", str(dest)]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"no wheel for CPython {python} on {platform}:\n{done.stderr.strip()[-800:]}")


def collect_hashes(pinned: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Normalised name -> SHA-256 of every wheel pip chooses across the matrix."""
    hashes: dict[str, set[str]] = {}
    with tempfile.TemporaryDirectory(prefix="sniper-hash-lock-") as tmp:
        requirements = Path(tmp) / "plain.txt"
        requirements.write_text("".join(f"{n}=={v}\n" for n, v in pinned), encoding="utf-8")
        wheels = Path(tmp) / "wheels"
        for python in PYTHONS:
            for platform in PLATFORMS:
                _download(requirements, python, platform, wheels)
        for wheel in sorted(wheels.iterdir()):
            name = _normal(wheel.name.split("-", 1)[0])
            hashes.setdefault(name, set()).add(hashlib.sha256(wheel.read_bytes()).hexdigest())
    missing = [n for n, _ in pinned if _normal(n) not in hashes]
    if missing:
        raise SystemExit(f"no wheel downloaded for: {', '.join(missing)}")
    return hashes


def _normal(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def render(pinned: list[tuple[str, str]], hashes: dict[str, set[str]]) -> str:
    """The lock text: a header, then each pin with all of its accepted hashes."""
    lines = ["# Pinned Python set this release is built and tested against, with the SHA-256",
             "# of every wheel pip may choose for CPython 3.12-3.14 on macOS 13+ arm64 (and on",
             "# macOS 14+ x86_64, untested). Regenerate with: python -m release.hash_lock",
             "# The installer runs: pip install --require-hashes --only-binary=:all: -r this-file"]
    for name, version in pinned:
        digests = sorted(hashes[_normal(name)])
        lines.append(f"{name}=={version} \\")
        lines += [f"    --hash=sha256:{d}" + (" \\" if i < len(digests) - 1 else "") for i, d in enumerate(digests)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 when stale")
    args = parser.parse_args(argv)
    pinned = pins(LOCK)
    text = render(pinned, collect_hashes(pinned))
    if args.check:
        stale = text != LOCK.read_text(encoding="utf-8")
        print("stale" if stale else "current")
        return 1 if stale else 0
    LOCK.write_text(text, encoding="utf-8")
    print(f"{len(pinned)} packages, {text.count('--hash=')} hashes -> {LOCK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
