"""Resolve governing instruction files into hashed, line-exact role packet sections.

Selectors (built by `role_packet_catalog`): an exact heading, a unique line-prefix range, one
paragraph or the whole document; `except` subtracts named sub-ranges from a section and `when`
assigns a section only when the subject uses a feature. Every excluded range is still resolved and
must match its content pin (the first 16 hex of the SHA-256 of its lines), so a renamed section or
text inserted into an excluded range fails closed until the catalog is reviewed; each exclusion is
recorded with its reason. A feature whose value is unknown (None, or no features) never excludes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from cut_preview_io import read_bytes
from role_packet_catalog import WHOLE

MAX_INSTRUCTION_BYTES = 4 * 1024 * 1024


class SectionError(ValueError):
    """A catalog selector no longer identifies exactly one current section."""


def markdown_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (index, level, text) for headings outside fenced code blocks."""
    rows, fenced = [], False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        level = len(line) - len(line.lstrip("#"))
        if not fenced and 1 <= level <= 6 and line[level:level + 1] == " ":
            rows.append((index, level, line.rstrip()))
    return rows


def heading_span(lines: list[str], title: str) -> tuple[int, int]:
    """Span one exact heading through the line before the next same-or-higher heading."""
    headings = markdown_headings(lines)
    matches = [row for row in headings if row[2] == title]
    if len(matches) != 1:
        raise SectionError(f"heading {title!r} matched {len(matches)} times")
    start, level, _text = matches[0]
    later = [index for index, other, _ in headings if index > start and other <= level]
    return start, (later[0] if later else len(lines)) - 1


def prefix_span(lines: list[str], start_prefix: str, end_prefix: str) -> tuple[int, int]:
    """Span a unique starting line up to the first later line with the end prefix ('' = the next blank line)."""
    starts = [index for index, line in enumerate(lines) if line.startswith(start_prefix)]
    if len(starts) != 1:
        raise SectionError(f"start {start_prefix!r} matched {len(starts)} times")
    ends = [index for index in range(starts[0] + 1, len(lines))
            if (lines[index].startswith(end_prefix) if end_prefix else not lines[index].strip())]
    if not ends:
        raise SectionError(f"end {end_prefix!r} does not follow {start_prefix!r}")
    return starts[0], ends[0] - 1


def base_range(lines: list[str], selector: tuple) -> dict:
    """One heading, prefix range or whole document as a titled, 1-based inclusive line range."""
    if selector[0] == "heading":
        start, end = heading_span(lines, selector[1])
        title = selector[1]
    elif selector[0] == "range":
        start, end = prefix_span(lines, selector[1], selector[2])
        title = lines[start].strip()[:160]
    elif selector[0] == "paragraph":
        start, end = prefix_span(lines, selector[1], "")
        title = lines[start].strip()[:160]
    elif selector[0] == "whole":
        start, end, title = 0, len(lines) - 1, "(whole document)"
    else:
        raise SectionError(f"unknown selector {selector[0]!r}")
    return {"title": title, "startLine": start + 1, "endLine": end + 1}


def absent(features: dict | None, feature: str) -> bool:
    """True only when the subject is known not to use the feature."""
    return features is not None and features.get(feature) is False


def pinned(lines: list[str], row: dict, pin: str | None) -> dict:
    """Refuse an excluded range whose content no longer matches the catalog's pin."""
    actual = hashlib.sha256("\n".join(lines[row["startLine"] - 1:row["endLine"]]).encode()).hexdigest()[:16]
    if pin != actual:
        raise SectionError(f"excluded range {row['title']!r} (lines {row['startLine']}-{row['endLine']}) no longer "
                           f"matches its catalog pin {pin} (now {actual}); review the new text and update the catalog")
    return row


def excluded_row(row: dict, reason: str, feature: str | None) -> dict:
    """A deliberately unassigned range with the maintained catalog's reason."""
    return {**row, "reason": reason, **({"condition": feature} if feature else {})}


def cut_rows(lines: list[str], outer: dict, drops: tuple, features: dict | None) -> list[tuple[dict, bool]]:
    """Resolve every exclusion inside its section (applied or not), refusing strays and overlaps."""
    rows, previous = [], 0
    resolved = sorted(((pinned(lines, base_range(lines, inner), pin), reason, feature)
                       for _kind, inner, reason, feature, pin in drops), key=lambda item: item[0]["startLine"])
    for row, reason, feature in resolved:
        if not outer["startLine"] <= row["startLine"] <= row["endLine"] <= outer["endLine"]:
            raise SectionError(f"exclusion {row['title']!r} lies outside {outer['title']!r}")
        if row["startLine"] <= previous:
            raise SectionError(f"exclusion {row['title']!r} overlaps another exclusion")
        previous = row["endLine"]
        rows.append((excluded_row(row, reason, feature), feature is None or absent(features, feature)))
    return rows


def subtract(lines: list[str], selector: tuple, features: dict | None) -> tuple[list[dict], list[dict]]:
    """A section minus its applied exclusions; once anything is cut, pieces are titled by their first line."""
    outer = base_range(lines, selector[1])
    applied = [row for row, active in cut_rows(lines, outer, selector[2], features) if active]
    kept, cursor = [], outer["startLine"]
    for row in applied + [{"startLine": outer["endLine"] + 1, "endLine": outer["endLine"]}]:
        if row["startLine"] > cursor:
            title = lines[cursor - 1].strip()[:160] if applied else outer["title"]
            kept.append({"title": title, "startLine": cursor, "endLine": row["startLine"] - 1})
        cursor = row["endLine"] + 1
    return kept, applied


def resolve_selector(lines: list[str], selector: tuple, features: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Assigned ranges and recorded exclusions for one catalog selector."""
    if selector[0] == "when":
        _kind, feature, inner, reason, pin = selector
        kept = [pinned(lines, base_range(lines, inner), pin)]
        if not absent(features, feature):
            return kept, []
        return [], [excluded_row(row, reason, feature) for row in kept]
    if selector[0] == "except":
        return subtract(lines, selector, features)
    return [base_range(lines, selector)], []


def assigned(lines: list[str], sections: list[dict]) -> dict:
    """Distinct assigned lines and their UTF-8 bytes (overlapping selectors count once)."""
    numbers = sorted({line for row in sections for line in range(row["startLine"], row["endLine"] + 1)})
    return {"lines": len(numbers), "bytes": sum(len(lines[number - 1].encode()) + 1 for number in numbers)}


def read_instruction(path: Path) -> tuple[str, list[str]]:
    """Hash exact bytes under the shared no-follow, single-link artifact rule."""
    raw = read_bytes(path, MAX_INSTRUCTION_BYTES)
    return hashlib.sha256(raw).hexdigest(), raw.decode("utf-8").splitlines()


def resolve_all(lines: list[str], selectors: tuple, features: dict | None) -> tuple[list[dict], list[dict]]:
    """Every selector of one catalog row, ordered by line."""
    kept, dropped = [], []
    for selector in (("whole",),) if selectors == WHOLE else selectors:
        rows, excluded = resolve_selector(lines, selector, features)
        kept += rows
        dropped += excluded
    return sorted(kept, key=line_order), sorted(dropped, key=line_order)


def line_order(row: dict) -> int:
    """Sort key: first line of a range."""
    return row["startLine"]


def instruction_row(repo: Path, spec: tuple, features: dict | None = None) -> dict:
    """Resolve one catalog row; any missing file or selector fails the whole packet."""
    relative, selectors, why = spec
    path = (repo / relative).resolve(strict=True)
    try:
        sha256, lines = read_instruction(path)
        sections, excluded = resolve_all(lines, selectors, features)
    except SectionError as error:
        raise SectionError(f"{relative}: {error}") from error
    whole = [(row["startLine"], row["endLine"]) for row in sections] == [(1, len(lines))]
    return {"path": str(path), "sha256": sha256, "lines": len(lines), "read": "whole" if whole else "sections",
            "sections": sections, "assigned": assigned(lines, sections), "excluded": excluded, "why": why}


def scoped_instruction_row(path: Path) -> dict:
    """Hash an ancestor/global AGENTS.md that governs the selected directory; read it whole."""
    canonical = path.resolve(strict=True)
    sha256, lines = read_instruction(canonical)
    sections = [{"title": "(whole document)", "startLine": 1, "endLine": len(lines)}]
    return {"path": str(canonical), "sha256": sha256, "lines": len(lines), "read": "whole", "sections": sections,
            "assigned": assigned(lines, sections), "excluded": [],
            "why": "Scoped AGENTS.md instructions that govern the selected directory."}


def instruction_rows(repo: Path, specs: tuple, scoped: list[Path], features: dict | None = None) -> list[dict]:
    """Catalog rows first, then scoped instruction files not already listed."""
    rows = [instruction_row(repo, spec, features) for spec in specs]
    seen = {row["path"] for row in rows}
    for path in scoped:
        row = scoped_instruction_row(path)
        if row["path"] not in seen:
            seen.add(row["path"])
            rows.append(row)
    return rows
