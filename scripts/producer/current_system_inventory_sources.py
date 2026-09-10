"""Bounded source selection for the current-system inventory audit."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditScope:
    """Production-source roots, extensions, and excluded path segments."""

    roots: tuple[str, ...]
    extensions: frozenset[str]
    excluded_segments: frozenset[str]


def _strings(value: object, label: str) -> tuple[str, ...]:
    invalid = (
        type(value) is not list
        or not value
        or any(type(item) is not str or not item for item in value)
        or len(set(value)) != len(value)
    )
    if invalid:
        raise RuntimeError(f"{label} must be unique nonempty strings")
    return tuple(value)


def parse_audit_scope(value: object) -> AuditScope:
    """Parse the closed inventory call-site search policy."""
    expected = {"roots", "extensions", "excludedPathSegments"}
    if type(value) is not dict or set(value) != expected:
        raise RuntimeError("callSiteAudit is malformed")
    return AuditScope(
        _strings(value["roots"], "callSiteAudit.roots"),
        frozenset(_strings(value["extensions"], "callSiteAudit.extensions")),
        frozenset(_strings(
            value["excludedPathSegments"],
            "callSiteAudit.excludedPathSegments",
        )),
    )


def _source_text(
    repo: Path, path: Path, scope: AuditScope,
) -> tuple[str, str] | None:
    relative = path.relative_to(repo)
    excluded = scope.excluded_segments.intersection(relative.parts)
    if (not path.is_file() or path.is_symlink()
            or path.suffix not in scope.extensions or excluded):
        return None
    key = relative.as_posix()
    try:
        return key, path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"audit source is not UTF-8: {key}") from exc


def _root_sources(
    repo: Path, root: Path, scope: AuditScope,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        source = _source_text(repo, path, scope)
        if source is not None:
            result[source[0]] = source[1]
    return result


def source_files(repo: Path, scope: AuditScope) -> dict[str, str]:
    """Read every UTF-8 production source selected by one audit scope."""
    sources: dict[str, str] = {}
    for relative_root in scope.roots:
        root = repo / relative_root
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError(f"audit root is unavailable: {relative_root}")
        sources.update(_root_sources(repo, root, scope))
    if not sources:
        raise RuntimeError("call-site audit scope selected no sources")
    return sources
