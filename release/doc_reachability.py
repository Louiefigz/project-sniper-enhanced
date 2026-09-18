#!/usr/bin/env python3
"""Which documents the shipped agent surfaces actually reach.

    python3 -m release.doc_reachability [--json]

Imports find nothing here: these documents are reached by name from skills,
commands, prompts, JSON contracts, subprocess arguments and other documents. So
the closure is computed over the text of every shipped surface, starting from
the roots the instruction chain names, and followed transitively.

The result is the input to the docs allow-list. A document outside the closure is
withheld with that reason recorded; it is never deleted upstream.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Where a document reference can be written down.
SURFACES = ("src", "scripts", "schemas", ".claude", ".agents", "templates")
ROOTS = ("AGENTS.md", "CLAUDE.md", "README.md", "docs/README.md", "docs/PIPELINE.md")
_REF = re.compile(r"(?:docs/)?[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:md|json)")
_TEXT = {".md", ".json", ".ts", ".tsx", ".js", ".mjs", ".py", ".html", ".css"}
_MAX = 2_000_000


def _text(path: Path) -> str:
    """Readable text of a file, or an empty string."""
    if path.suffix.lower() not in _TEXT or path.stat().st_size > _MAX:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _candidates(text: str) -> set[str]:
    """Every doc-shaped reference written in this text, normalised under docs/."""
    found: set[str] = set()
    for raw in _REF.findall(text):
        cleaned = raw.lstrip("./")
        if cleaned.startswith("docs/"):
            found.add(cleaned)
        elif "/" not in cleaned:
            found.add(f"docs/{cleaned}")
        else:
            found.add(cleaned)
    return found


def surface_references() -> set[str]:
    """Doc references written anywhere in the shipped code and agent surfaces."""
    found: set[str] = set()
    for surface in SURFACES:
        base = ROOT / surface
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                found |= _candidates(_text(path))
    for name in ROOTS:
        path = ROOT / name
        if path.exists():
            found |= _candidates(_text(path))
    return found


def _resolve(reference: str) -> Path | None:
    """The shipped document a reference names, if it exists under docs/."""
    direct = ROOT / reference
    if direct.is_file():
        return direct
    tail = reference.split("/")[-1]
    matches = sorted((ROOT / "docs").rglob(tail))
    return matches[0] if len(matches) == 1 else None


def closure() -> tuple[set[str], set[str]]:
    """Reachable documents under docs/, and references that resolve to nothing.

    Returns:
        A pair of (reachable relative paths, unresolved references).
    """
    pending = surface_references()
    seen: set[str] = set()
    reachable: set[str] = set()
    unresolved: set[str] = set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        path = _resolve(reference)
        if path is None:
            if reference.startswith("docs/"):
                unresolved.add(reference)
            continue
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith("docs/"):
            continue
        reachable.add(relative)
        pending |= _candidates(_text(path)) - seen
    return reachable, unresolved


def main(argv: list[str] | None = None) -> int:
    """Print the closure, and the documents under docs/ that fall outside it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    reachable, unresolved = closure()
    everything = {p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*")
                  if p.is_file()}
    outside = sorted(everything - reachable)
    if args.json:
        print(json.dumps({"reachable": sorted(reachable), "outside": outside,
                          "unresolved": sorted(unresolved)}, indent=2))
        return 0
    print(f"docs/ files total : {len(everything)}")
    print(f"reached by a surface: {len(reachable)}")
    print(f"outside the closure : {len(outside)}")
    print(f"references that resolve to nothing: {len(unresolved)}")
    for reference in sorted(unresolved)[:20]:
        print(f"  unresolved: {reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
