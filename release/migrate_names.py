#!/usr/bin/env python3
"""One-time migration: replace teacher-named identifiers with neutral ones.

    python3 -m release.migrate_names --dry-run
    python3 -m release.migrate_names

Maintainer tooling. It is **not** shipped, and neither is the legacy mapping it
carries: the accepted rule is that no teacher name appears in the distributed
product, which a compatibility alias table inside the runtime would violate.
Existing saved projects are converted separately by
`release.normalize_project`, which imports the same table from here.

The names are identifiers, not labels — `STYLES`, `PACES`, preset ids, the
`pacing_<pace>` lint-profile keys, composition filenames, `comp_capabilities`
keys, CSS custom properties and card-form selection tables all carry them — so
every surface has to move in one step or the cross-language drift tests fail,
which is them working correctly.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ordered: a longer form must win over a prefix of itself (jadenly before jaden,
# nate-herk before nateherk). Each case variant is listed explicitly so the
# replacement preserves the casing convention of the site it replaces.
MAPPING: tuple[tuple[str, str], ...] = (
    ("NATE HERK", "MODULE"), ("Nate Herk", "Module"), ("nate herk", "module"),
    ("nate-herk", "module"), ("NATE-HERK", "MODULE"), ("Nate-Herk", "Module"),
    ("NATEHERK", "MODULE"), ("Nateherk", "Module"), ("NateHerk", "Module"),
    ("nateherk", "module"),
    ("CALEB", "RESTRAINED"), ("Caleb", "Restrained"), ("caleb", "restrained"),
    ("JADENLY", "PUNCH"), ("Jadenly", "Punch"), ("jadenly", "punch"),
    ("JADEN", "PUNCH"), ("Jaden", "Punch"), ("jaden", "punch"),
    ("ANGELA", "SLIDEWARE"), ("Angela", "Slideware"), ("angela", "slideware"),
)

# Surfaces that ship, plus the docs the shipped skills read.
SURFACES = ("src", "scripts", "schemas", "templates", ".claude", ".agents",
            "assets", "public", "docs")
ROOT_FILES = ("AGENTS.md", "CLAUDE.md", "README.md")
SKIP_PARTS = frozenset({".git", "node_modules", ".venv", "__pycache__", ".next",
                        ".pytest_cache", "release", "artifacts",
                        ".sniper-native-runtime", "renders"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".ts", ".tsx", ".js", ".mjs",
                           ".cjs", ".py", ".html", ".css", ".yaml", ".yml",
                           ".example", ".markdown", ".svg"})
_FINDER = re.compile("|".join(re.escape(old) for old, _ in MAPPING))
_REPLACE = dict(MAPPING)


def _skipped(path: Path) -> bool:
    """Whether this path lies inside a directory the migration never touches."""
    return any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)


def candidates() -> list[Path]:
    """Every file in a shipped surface the migration may rewrite or rename."""
    found: list[Path] = []
    for name in ROOT_FILES:
        path = ROOT / name
        if path.is_file():
            found.append(path)
    for surface in SURFACES:
        base = ROOT / surface
        if not base.exists():
            continue
        found.extend(path for path in base.rglob("*")
                     if path.is_file() and not path.is_symlink() and not _skipped(path))
    return sorted(found)


def convert(text: str) -> str:
    """Apply the whole mapping to one blob of text."""
    return _FINDER.sub(lambda match: _REPLACE[match.group(0)], text)


def rewrite(path: Path, dry_run: bool) -> int:
    """Rewrite one file's contents.

    Args:
        path: File to rewrite.
        dry_run: Report only.

    Returns:
        Occurrences replaced.
    """
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    found = len(_FINDER.findall(text))
    if found and not dry_run:
        path.write_text(convert(text), encoding="utf-8")
    return found


def renames(paths: list[Path]) -> list[tuple[Path, Path]]:
    """Files whose own name carries a teacher name, deepest first."""
    pairs: list[tuple[Path, Path]] = []
    for path in paths:
        if _FINDER.search(path.name):
            pairs.append((path, path.with_name(convert(path.name))))
    return sorted(pairs, key=lambda pair: len(pair[0].parts), reverse=True)


def main(argv: list[str] | None = None) -> int:
    """Run or preview the migration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    paths = candidates()
    total, touched = 0, 0
    for path in paths:
        found = rewrite(path, args.dry_run)
        if found:
            total, touched = total + found, touched + 1
    pairs = renames(paths)
    for source, target in pairs:
        if target.exists() and target != source:
            print(f"REFUSED: {target.relative_to(ROOT)} already exists")
            return 2
        print(f"{'would rename' if args.dry_run else 'renamed'} "
              f"{source.relative_to(ROOT)} -> {target.name}")
        if not args.dry_run:
            source.rename(target)
    print(f"{total} occurrences in {touched} files; {len(pairs)} files renamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
