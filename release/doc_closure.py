#!/usr/bin/env python3
"""The operational documents the shipped product actually needs.

    python3 -m release.doc_closure > release/operational-docs.json

Three sources, no transitive walk into history:
  1. every `docs/...md` or `scripts/producer/docs/...md` path named in shipped
     non-test code (the runtime reads these, e.g. the Auto Edit doctrine pins);
  2. every document linked directly from a shipped instruction surface — skills,
     commands, AGENTS.md, CLAUDE.md, README.md, docs/PIPELINE.md, docs/README.md
     and scripts/producer/CLAUDE.md;
  3. the named workflow documents the release brief requires.

Dated development history reached only through those documents is withheld: it
records internal evidence, client work and third-party study material, and no
shipped surface needs it to operate. Internal audits (docs/audits/) ship only when
shipped code names them (the runtime reads them); a link from an index is not enough. A link from a shipped document into that
history is recorded by the builder as withheld, not silently followed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LINK = re.compile(r"\]\(([^)#\s]+\.(?:md|json))(?:#[^)]*)?\)|`((?:docs|scripts/producer/docs)/[^`\s]+\.md)`"
                   r"|\"((?:docs|scripts/producer/docs)/[^\"]+\.md)\"")
_CODE = re.compile(r'"((?:docs|scripts/producer/docs)/[^"]+\.md)"')
REQUIRED = (
    "docs/PIPELINE.md", "docs/README.md",
    "docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md",
    "docs/producer/NATIVE_SHORTS_WORKFLOW.md", "docs/producer/NATIVE_LONG_EXPORT.md",
    "docs/producer/NATIVE_LONG_SELECTED_SOURCES.md", "docs/producer/NATIVE_PREFLIGHT.md",
    "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md",
    "docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md", "docs/producer/STUDIO_REVIEW_LANE.md",
    "docs/producer/WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md", "docs/producer/CONTEXT_ENTRY.md",
)
WITHHELD = ("STUDENT_KIT", "SHORTS_STYLE_SELECTION")  # third-party kit audit; creator-library study


def _surfaces() -> list[Path]:
    found = [*ROOT.glob(".claude/skills/**/*.md"), *ROOT.glob(".agents/skills/**/*.md"),
             *ROOT.glob(".claude/commands/*.md")]
    found += [ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "README.md", "docs/PIPELINE.md",
                                       "docs/README.md", "scripts/producer/CLAUDE.md")]
    return [path for path in found if path.is_file()]


def _linked(doc: Path) -> set[str]:
    out: set[str] = set()
    for match in _LINK.finditer(doc.read_text(encoding="utf-8", errors="ignore")):
        target = next(group for group in match.groups() if group)
        if target.startswith("http"):
            continue
        base = ROOT if target.startswith(("docs/", "scripts/")) else doc.parent
        try:
            relative = (base / target).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if relative.startswith(("docs/", "scripts/producer/docs/")) and (ROOT / relative).is_file():
            out.add(relative)
    return out


def _named_in_code() -> set[str]:
    out: set[str] = set()
    for pattern in ("src/**/*.ts", "scripts/**/*.py"):
        for path in ROOT.glob(pattern):
            if "__tests__" in path.parts or "tests" in path.parts or "__pycache__" in path.parts:
                continue
            out |= set(_CODE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return out


def closure() -> list[str]:
    """The sorted operational document list (docs/ only; scripts/ ships whole)."""
    named = _named_in_code()
    wanted = set(REQUIRED) | named
    for surface in _surfaces():
        wanted |= {doc for doc in _linked(surface) if not doc.startswith("docs/audits/") or doc in named}
    return sorted(doc for doc in wanted if doc.startswith("docs/") and (ROOT / doc).is_file()
                  and not any(mark in doc for mark in WITHHELD))


if __name__ == "__main__":
    print(json.dumps(closure(), indent=1))
