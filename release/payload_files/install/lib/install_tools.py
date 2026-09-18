#!/usr/bin/env python3
"""Integrity helpers the installer uses to decide whether a finished step is still intact.

    install_tools.py tree-record <dir> <record.json> [--exclude NAME ...]
    install_tools.py tree-check  <dir> <record.json> [--exclude NAME ...]
    install_tools.py venv-check  <requirements.lock.txt>   (run with the venv's python)

A tree record holds the SHA-256 of every regular file (and the target of every
symlink) under a folder, taken when the step finished; ``--exclude`` names folders
(relative to it) that the product itself rewrites later, such as ``.next/cache``.
`tree-check` re-hashes the folder and exits 1 naming what changed, so a corrupted, truncated or half-removed
dependency folder is reinstalled instead of trusted. `venv-check` compares the
installed distributions with the lock and re-hashes every file pip recorded in
each distribution's RECORD. Standard library only: it runs before the app's
virtual environment exists.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def file_digest(path: Path) -> str:
    """SHA-256 of one file, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _entries(root: Path, exclude: set[str]) -> dict[str, Path | str]:
    """Relative path -> file to hash, or 'link:<target>' for a symlink.

    ``exclude`` holds folder paths relative to ``root`` (e.g. ``cache`` for
    ``.next/cache``) whose contents legitimately change after the step finished.
    """
    found: dict[str, Path | str] = {}
    for current, dirs, files in os.walk(root):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if (base / d).relative_to(root).as_posix() not in exclude)
        for name in dirs:
            if (base / name).is_symlink():
                found[(base / name).relative_to(root).as_posix()] = "link:" + os.readlink(base / name)
        for name in sorted(files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            found[relative] = "link:" + os.readlink(path) if path.is_symlink() else path
    return found


def tree_digests(root: Path, exclude: set[str]) -> dict[str, str]:
    """Every file's digest under ``root``, hashed in parallel (hashlib releases the GIL)."""
    entries = _entries(root, exclude)
    files = [(rel, path) for rel, path in entries.items() if isinstance(path, Path)]
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2))) as pool:
        hashed = dict(zip((rel for rel, _ in files), pool.map(file_digest, (p for _, p in files))))
    return {rel: hashed.get(rel, value) if isinstance(value, Path) else value
            for rel, value in sorted(entries.items())}


def tree_record(root: Path, record: Path, exclude: set[str]) -> int:
    """Write the record of a folder a step just finished."""
    digests = tree_digests(root, exclude)
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix(".tmp")
    temporary.write_text(json.dumps({"files": digests}, sort_keys=True), encoding="utf-8")
    temporary.replace(record)
    print(f"{len(digests)} files recorded")
    return 0


def tree_check(root: Path, record: Path, exclude: set[str]) -> int:
    """Exit 0 when the folder is exactly as recorded, 1 (with a summary) otherwise."""
    try:
        want = json.loads(record.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        print("no usable record of the finished step")
        return 1
    if not root.is_dir():
        print("the folder is missing")
        return 1
    have = tree_digests(root, exclude)
    changed = sorted(k for k in want if k in have and have[k] != want[k])
    missing = sorted(k for k in want if k not in have)
    added = sorted(k for k in have if k not in want)
    if not (changed or missing or added):
        return 0
    example = (changed or missing or added)[0]
    print(f"{len(changed)} changed, {len(missing)} missing, {len(added)} unexpected (e.g. {example})")
    return 1


def _lock_pins(lock: Path) -> dict[str, str]:
    """name (normalised) -> version from a hashed requirements lock."""
    pins: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        text = line.strip().rstrip("\\").strip()
        if not text or text.startswith(("#", "--")) or "==" not in text:
            continue
        name, version = text.split("==", 1)
        pins[_normal(name)] = version.split(";")[0].split()[0]
    return pins


def _normal(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def _record_problems(dist) -> list[str]:
    """Files of one installed distribution whose bytes differ from its RECORD."""
    problems = []
    for entry in dist.files or []:
        if not entry.hash or entry.hash.mode != "sha256":
            continue
        path = Path(dist.locate_file(entry))
        if not path.is_file():
            problems.append(f"{entry} missing")
            continue
        with path.open("rb") as handle:
            actual = base64.urlsafe_b64encode(hashlib.sha256(handle.read()).digest()).rstrip(b"=").decode()
        if actual != entry.hash.value:
            problems.append(f"{entry} changed")
    return problems


def venv_check(lock: Path) -> int:
    """Exit 0 when this interpreter's environment is exactly the lock and every file verifies."""
    from importlib import metadata  # noqa: PLC0415
    pins = _lock_pins(lock)
    site = [p for p in sys.path if p.endswith("site-packages")]
    dists = {_normal(d.metadata["Name"]): d for d in metadata.distributions(path=site)}
    problems = [f"{name} {dists[name].version if name in dists else 'missing'} (want {version})"
                for name, version in pins.items()
                if name not in dists or dists[name].version != version]
    for name in sorted(pins):
        if name in dists:
            problems += _record_problems(dists[name])
    if problems:
        print(f"{len(problems)} problem(s), e.g. {problems[0]}")
        return 1
    print(f"{len(pins)} pinned packages installed and verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("tree-record", "tree-check"):
        cmd = sub.add_parser(name)
        cmd.add_argument("root", type=Path)
        cmd.add_argument("record", type=Path)
        cmd.add_argument("--exclude", action="append", default=[])
    sub.add_parser("venv-check").add_argument("lock", type=Path)
    args = parser.parse_args(argv)
    if args.action == "venv-check":
        return venv_check(args.lock)
    handler = tree_record if args.action == "tree-record" else tree_check
    return handler(args.root, args.record, set(args.exclude))


if __name__ == "__main__":
    raise SystemExit(main())
