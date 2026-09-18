"""Explicit source-color cold-read transport, not authenticated read authority.

The server must separately authenticate the stopped-process sidecar and the
final-cleanup reservation archive. This module checks supplied spelling only:
it reads no files, starts no clocks, discovers no tools and creates no owners.
Partial flags never become a legacy read or an inferred reservation location.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from weakref import WeakKeyDictionary

from guided_source_color_staging_contract import _hash, _path


_TRANSPORTS: WeakKeyDictionary = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class SourceColorReadTransport:
    """Four original server-supplied fields, without execution or cleanup powers."""

    input_path: Path
    input_sha256: str
    archive_path: Path
    archive_sha256: str

    def __post_init__(self) -> None:
        """Validate and retain original fields before any caller IO or callback."""
        _TRANSPORTS[self] = _fields(self)


def _fields(value: SourceColorReadTransport) -> tuple:
    """Keep exact path objects and original scalar values without normalization."""
    if type(value) is not SourceColorReadTransport or set(vars(value)) != {
            "input_path", "input_sha256", "archive_path", "archive_sha256"}:
        raise ValueError("source-color read requires the exact optional transport")
    paths = value.input_path, value.archive_path
    if any(type(path) is not type(Path()) for path in paths):
        raise ValueError("source-color read transport path types differ")
    for path in paths:
        _path(str(path))
    return (tuple((id(path), str(path)) for path in paths),
            _hash(value.input_sha256), _hash(value.archive_sha256))


def parse_source_color_read_transport(values: tuple) -> SourceColorReadTransport | None:
    """Require all four optional flag strings or none, without filesystem work.

    Args:
        values: Sidecar path/SHA followed by reservation archive path/SHA.

    Returns:
        Original lexical transport, or None for the unchanged legacy route.
    """
    if type(values) is not tuple or len(values) != 4:
        raise ValueError("source-color read requires exactly four optional fields")
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("all four source-color read flags must be supplied together")
    location, sha256, archive, archive_sha256 = values
    return SourceColorReadTransport(Path(_path(location)), _hash(sha256),
                                    Path(_path(archive)), _hash(archive_sha256))


def validate_source_color_read_transport(value: SourceColorReadTransport | None) -> None:
    """Reject malformed direct calls and changed originals before clock/file IO."""
    if value is None:
        return
    if _fields(value) != _TRANSPORTS.get(value):
        raise RuntimeError("source-color original read transport changed")
