"""Stage the allow-listed release tree and scan it before anything is archived.

The staged tree is the only input to the archive. Nothing is zipped from the
development folder, and the scan fails the build closed rather than reporting a
warning.
"""
from __future__ import annotations

import fnmatch
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from release import package_spec as spec

_TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".json", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".py", ".html",
    ".css", ".sh", ".command", ".yml", ".yaml", ".example", ".markdown", ".svg",
})
_SCAN_MAX_BYTES = 4_000_000


class StagingError(RuntimeError):
    """A staged tree failed a fail-closed check."""


@dataclass
class StageReport:
    """Outcome of one staging run."""

    files: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def fail_if_findings(self) -> None:
        """Raise with every finding, never with the matched value."""
        if self.findings:
            joined = "\n  ".join(self.findings)
            raise StagingError(f"staged tree failed inspection:\n  {joined}")


def _denied_dir(relative: str) -> str | None:
    """Reason this directory is withheld, or None."""
    parts = relative.split("/")
    for name, reason in spec.EXCLUDE_DIRS:
        target = name.split("/")
        if parts[: len(target)] == target or name in parts:
            return reason
    return None


def _denied_glob(relative: str) -> str | None:
    """Reason this file is withheld by a glob rule, or None."""
    base = relative.rsplit("/", 1)[-1]
    for pattern, reason in spec.EXCLUDE_GLOBS:
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(base, pattern):
            return reason
    return None


def _copy_file(source: Path, target: Path) -> None:
    """Copy one regular file, preserving mode but never metadata or xattrs."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(source.stat().st_mode & 0o755)


def _walk_include(root: Path, entry: str, dest: Path, report: StageReport) -> None:
    """Stage one INCLUDE entry, applying the withhold rules underneath it."""
    source = root / entry
    if not source.exists():
        raise StagingError(f"allow-listed path is missing from the release source: {entry}")
    if source.is_file():
        _copy_file(source, dest / entry)
        report.files.append(entry)
        return
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            report.skipped.append((relative, "symlink: never archived"))
            continue
        if path.is_dir():
            continue
        reason = _denied_dir(relative) or _denied_glob(relative)
        if reason:
            report.skipped.append((relative, reason))
            continue
        _copy_file(path, dest / relative)
        report.files.append(relative)


def stage_tree(root: Path, dest: Path, report: StageReport) -> None:
    """Copy every allow-listed path into a clean staging directory.

    Args:
        root: The isolated release source root.
        dest: Empty staging directory to fill.
        report: Accumulates staged files, withheld paths and findings.

    Raises:
        StagingError: An allow-listed path does not exist.
    """
    for entry, reason in spec.INCLUDE:
        if entry == "@operational-docs":
            import json  # noqa: PLC0415
            for doc in json.loads((root / reason).read_text(encoding="utf-8")):
                _walk_include(root, doc, dest, report)
            continue
        _walk_include(root, entry, dest, report)


def _readable_text(path: Path) -> str | None:
    """Text of a scannable file, or None when it is binary or oversized."""
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    if path.stat().st_size > _SCAN_MAX_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def scan_paths(dest: Path, report: StageReport) -> None:
    """Fail closed on a withheld shape in any staged path name."""
    rules = [(re.compile(pattern), reason) for pattern, reason in spec.DENY_PATH]
    for relative in report.files:
        for expression, reason in rules:
            if expression.search(relative):
                report.findings.append(f"{relative}: {reason}")


def scan_content(dest: Path, report: StageReport) -> None:
    """Fail closed on a credential shape in any staged text file."""
    rules = [(re.compile(pattern), reason) for pattern, reason in spec.DENY_CONTENT]
    for relative in report.files:
        text = _readable_text(dest / relative)
        if text is None:
            continue
        for expression, reason in rules:
            match = expression.search(text)
            if match:
                line = text[: match.start()].count("\n") + 1
                report.findings.append(f"{relative}:{line}: {reason} (value not printed)")


def scan_buyer_text(dest: Path, subtree: str, report: StageReport) -> None:
    """Fail closed on a withheld claim or name in buyer-visible text."""
    rules = [(re.compile(pattern), reason) for pattern, reason in spec.DENY_BUYER_TEXT]
    base = dest / subtree
    if not base.exists():
        raise StagingError(f"buyer-visible subtree is missing: {subtree}")
    for path in sorted(base.rglob("*")):
        text = _readable_text(path) if path.is_file() else None
        if text is None:
            continue
        relative = path.relative_to(dest).as_posix()
        for expression, reason in rules:
            match = expression.search(text)
            if match:
                line = text[: match.start()].count("\n") + 1
                report.findings.append(f"{relative}:{line}: buyer text: {reason}")


def scan_shipped_text(dest: Path, report: StageReport) -> None:
    """Record teacher names appearing in the text of shipped source and docs.

    Reported in the same class as the path rule so the pending-rename list is
    complete: the accepted decision covers the whole distributed product, not
    only its filenames.
    """
    rules = [(re.compile(pattern), reason) for pattern, reason in spec.DENY_SHIPPED_TEXT]
    for relative in report.files:
        text = _readable_text(dest / relative)
        if text is None:
            continue
        for expression, reason in rules:
            match = expression.search(text)
            if match:
                line = text[: match.start()].count("\n") + 1
                report.findings.append(f"{relative}:{line}: {reason}")
                break
