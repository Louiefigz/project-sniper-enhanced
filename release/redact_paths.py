#!/usr/bin/env python3
"""Remove the maintainer's home path from the release source.

    python3 -m release.redact_paths [--check]

The product's recorded calibration and evidence documents are read by code —
`baseline_repeat_validation.py` and `current_system_inventory_check.py` both load
contracts under `docs/producer/command-driven-editing/contracts/` — so they
cannot simply be withheld. What they must not carry into a buyer's hands is the
maintainer's username.

This rewrites the absolute prefixes in place, which preserves each record's
shape and every hash in it. Nothing but the path text changes. Run the full test
suites afterwards: the suites, not this tool, establish that nothing broke.

`--check` reports remaining occurrences and changes nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Longest first: the project prefix must win over the bare home prefix.
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER",
     "/Users/maintainer/ProjectSniperSource"),
    ("/Users/aaronfigueroa/development/demos/YT-Automation",
     "/Users/maintainer/workspace"),
    ("/Users/aaronfigueroa", "/Users/maintainer"),
)
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "artifacts",
                       ".next", ".pytest_cache", "release"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".ts", ".tsx", ".js", ".mjs", ".cjs",
                           ".py", ".html", ".css", ".sh", ".command", ".yml", ".yaml",
                           ".example", ".markdown", ".vtt", ".srt"})
_NEEDLE = re.compile(r"/Users/aaronfigueroa")
_MAX = 40_000_000


def candidates() -> list[Path]:
    """Every text file in the release source that redaction may touch."""
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts[:-1]):
            continue
        if path.name in SKIP_DIRS or not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= _MAX:
            found.append(path)
    return sorted(found)


def redact(path: Path) -> int:
    """Rewrite one file's maintainer paths.

    Args:
        path: File to rewrite.

    Returns:
        Number of occurrences replaced; 0 leaves the file untouched.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    if not _NEEDLE.search(text):
        return 0
    count = len(_NEEDLE.findall(text))
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return count


def main(argv: list[str] | None = None) -> int:
    """Redact, or report what remains."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    files, total = 0, 0
    for path in candidates():
        if args.check:
            try:
                hits = len(_NEEDLE.findall(path.read_text(encoding="utf-8")))
            except (UnicodeDecodeError, OSError):
                hits = 0
            if hits:
                files, total = files + 1, total + hits
                print(f"  {path.relative_to(ROOT)}: {hits}")
            continue
        replaced = redact(path)
        if replaced:
            files, total = files + 1, total + replaced
            print(f"  redacted {path.relative_to(ROOT)}: {replaced}")
    verb = "remaining in" if args.check else "replaced across"
    print(f"{total} occurrences {verb} {files} files")
    if args.check and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
