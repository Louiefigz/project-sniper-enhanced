"""Original cold-read control identities captured BEFORE the first metadata read.

These stat holds are not raw-hash, execution or cleanup authority. The ordinary
readers still authenticate supplied hashes. Keeping the same initial files
closes replacements during early claim/input reads before the full scope exists.
No source byte, active reservation, original socket or executable is opened.
"""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from weakref import WeakKeyDictionary

from guided_body_execution import BodyHeldFile, _identity, _parent_paths, _directory_states
from guided_opening_execution import OpeningExecutionClock
from guided_source_color_read_transport import validate_source_color_read_transport
from guided_source_color_staging_contract import _path
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_read_clock import (source_color_read_clock_fields,
    source_color_read_remaining, source_color_read_wall, advance_source_color_read_wall)

_ENTRIES = WeakKeyDictionary()
_CUTOFFS = WeakKeyDictionary()
_WATERMARKS = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class SourceColorReadEntry:
    """One registered original stat-only capture, with no runtime/resource powers."""

    files: tuple
    parents: tuple
    states: tuple


def _fields(value: SourceColorReadEntry) -> tuple:
    """Keep original typed rows, path identities and complete ancestry immutable."""
    if type(value) is not SourceColorReadEntry or set(vars(value)) != {"files", "parents", "states"}:
        raise RuntimeError("source-color read needs its original entry capture")
    return (id(value.files), tuple((id(row), id(row.path), str(row.path), row.sha256, row.identity) for row in value.files),
            id(value.parents), tuple((id(path), str(path)) for path in value.parents), value.states)


def _clock_fields(clock: OpeningExecutionClock) -> tuple:
    """Bind actual clock identity/cutoff before the first filesystem or timing callback."""
    return source_color_read_clock_fields(clock)


def _cutoff(value: SourceColorReadEntry, clock: OpeningExecutionClock) -> None:
    """Keep the original clock and its earlier event prefix while allowing real later phases."""
    fields, count, prefix = _CUTOFFS[value]
    if not same_read_metadata(_clock_fields(clock), fields) or not same_read_metadata(clock.events[:count], prefix):
        raise RuntimeError("source-color read original entry clock or event prefix changed")
    _WATERMARKS[value] = advance_source_color_read_wall(clock, _WATERMARKS[value])


def assert_source_color_read_entry(value: SourceColorReadEntry, clock: OpeningExecutionClock) -> None:
    """Recheck original metadata/ancestry and SAME cutoff without a new hash or callback."""
    original = _ENTRIES.get(value)
    if original is None or not same_read_metadata(_fields(value), original):
        raise RuntimeError("source-color read original entry capture changed")
    _cutoff(value, clock)
    source_color_read_remaining(clock)
    _cutoff(value, clock)
    if _directory_states(value.parents) != value.states \
            or any(_identity(row.path.lstat()) != row.identity for row in value.files) \
            or _directory_states(value.parents) != value.states:
        raise RuntimeError("source-color read original entry file or ancestry changed")
    _cutoff(value, clock)
    source_color_read_remaining(clock)
    _cutoff(value, clock)


def capture_source_color_read_entry(paths: tuple, held: object, transport: object,
                                    clock: OpeningExecutionClock) -> SourceColorReadEntry:
    """Capture exact six control roles before the first ordinary result/claim read."""
    origin = hold_read_metadata(_clock_fields(clock)), len(clock.events), hold_read_metadata(clock.events)
    watermark = source_color_read_wall(clock)
    validate_source_color_read_transport(transport)
    input_path, root = paths
    expected = ((input_path, held.input_sha256, 128 * 1024), (held.claim_path, held.claim_sha256, 128 * 1024),
                (root / "media-result.json", held.receipt_sha256, 16 * 1024 ** 2),
                (transport.input_path, transport.input_sha256, 8 * 1024 ** 2),
                (transport.archive_path, transport.archive_sha256, 8 * 1024 ** 2),
                (root / "source-color-evidence.json", "", 16 * 1024 ** 2))
    rows = []
    parents = _parent_paths(tuple(BodyHeldFile(path, sha, ()) for path, sha, _maximum in expected))
    states = _directory_states(parents)
    for path, sha, maximum in expected:
        source_color_read_remaining(clock)
        watermark = advance_source_color_read_wall(clock, watermark)
        _path(str(path))
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise RuntimeError("source-color read entry requires bounded original regular files")
        rows.append(BodyHeldFile(path, sha, _identity(info)))
    value = SourceColorReadEntry(tuple(rows), parents, states)
    _ENTRIES[value] = hold_read_metadata(_fields(value))
    _CUTOFFS[value] = origin
    _WATERMARKS[value] = advance_source_color_read_wall(clock, watermark)
    assert_source_color_read_entry(value, clock)
    return value
