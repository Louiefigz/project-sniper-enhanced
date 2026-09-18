"""Bounded opt-in publication with staged bytes and ordinary-error rollback.

This is not a multi-file atomic transaction. A process crash leaves a pending
marker and retained old/new bytes; the opt-in assembler and graph reader reject
that state. A released GUI must still use its outer private-artifact promotion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from cut_preview_io import file_hash, read_bytes, write_new

PENDING_PUBLICATION = ".source-audio-publication.v2.json"
CAPTION_SHARD_NAME = re.compile(r"caption-shard-[0-9a-f]{64}\.mov(?:\.json)?")


@dataclass(frozen=True)
class Publication:
    """Exact prepared new bytes and retained originals for one output group."""

    root: Path
    directory: Path
    after: dict[str, str]
    before: dict[str, str | None]


def require_settled(root: Path) -> None:
    """An interrupted public opt-in write requires explicit recovery, not reuse."""
    marker = root / PENDING_PUBLICATION
    if marker.exists() or marker.is_symlink():
        raise RuntimeError("source-float publication is unresolved; retained recovery evidence")


def optional_hash(path: Path) -> str | None:
    """Absent is not a linked, malformed or unreadable existing public output."""
    return file_hash(path) if path.exists() or path.is_symlink() else None


def _copy_bounded(reader: BinaryIO, writer: BinaryIO, remaining: int) -> None:
    """Copy only the initially observed bytes, never an indefinitely growing file."""
    while remaining:
        data = reader.read(min(remaining, 1024 * 1024))
        if not data:
            raise RuntimeError("source-float generated support truncated")
        writer.write(data)
        remaining -= len(data)


def copy_verified(source: Path, destination: Path, expected: str) -> None:
    """Stage and replace a same-byte regular copy without following a source link."""
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        staged_fd, staged_name = tempfile.mkstemp(prefix=".source-audio-copy-", dir=destination.parent)
    except OSError:
        os.close(source_fd)
        raise
    staged = Path(staged_name)
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 2 * 1024 ** 3:
            raise RuntimeError("source-float generated support is not regular")
        with os.fdopen(source_fd, "rb", closefd=False) as reader, os.fdopen(staged_fd, "wb", closefd=False) as writer:
            _copy_bounded(reader, writer, info.st_size)
            writer.flush()
            os.fsync(staged_fd)
        if file_hash(staged) != expected or file_hash(source) != expected:
            raise RuntimeError("source-float support changed before publication")
        os.replace(staged, destination)
    finally:
        os.close(source_fd)
        os.close(staged_fd)
        staged.unlink(missing_ok=True)


def _caption_seed_names(root: Path, held: dict[str, str | None]) -> set[str]:
    """Select the prior active shard set, not every obsolete page from old edits."""
    path = root / "caption_shards.json"
    expected = held.get(str(path))
    if expected is None:
        return set()
    raw = read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("caption cache manifest changed from its original hold")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(record, dict) or not isinstance(record.get("entries"), list):
        return set()
    names = set()
    for row in record["entries"]:
        media = row.get("media") if isinstance(row, dict) else None
        name = media.get("name") if isinstance(media, dict) else None
        if isinstance(name, str) and CAPTION_SHARD_NAME.fullmatch(name) and name.endswith(".mov"):
            names.add(name)
    return names


def stage_caption_shards(root: Path, directory: Path, held: dict[str, str | None]) -> None:
    """Copy only originally held pairs; the existing renderer must revalidate them.

    These are untrusted cache candidates, not accepted artifacts. No final,
    caption-free composite, placements or generated authority is imported.
    Originals stay under the caller's existing publication holds.
    """
    for name in sorted(_caption_seed_names(root, held)):
        media = root / name
        expected = held.get(str(media))
        if expected is None:
            continue
        receipt = Path(str(media) + ".json")
        receipt_hash = held.get(str(receipt))
        if receipt_hash is None:
            continue
        copy_verified(media, directory / media.name, expected)
        copy_verified(receipt, directory / receipt.name, receipt_hash)


def _prepare(root: Path, entries: dict[str, tuple[Path, str]], before: dict[str, str | None]) -> Publication:
    """Finish every copy and exact previous-byte backup before public mutation."""
    require_settled(root)
    directory = Path(tempfile.mkdtemp(prefix=".source-audio-publication-", dir=root))
    (directory / "old").mkdir()
    (directory / "new").mkdir()
    for name, (source, expected) in entries.items():
        if Path(name).name != name or name in {".", "..", PENDING_PUBLICATION}:
            raise RuntimeError("source-float publication name is not owned")
        prior = before.get(str(root / name))
        if optional_hash(root / name) != prior:
            raise RuntimeError("source-float public support changed before publication")
        if prior is not None:
            copy_verified(root / name, directory / "old" / name, prior)
        copy_verified(source, directory / "new" / name, expected)
    return Publication(root, directory, {name: value[1] for name, value in entries.items()},
        {name: before.get(str(root / name)) for name in entries})


def _journal(item: Publication) -> dict:
    """Retain complete recovery facts without treating them as render approval."""
    return {"schemaVersion": 2, "kind": "unapproved-source-audio-publication",
        "directory": str(item.directory), "before": item.before, "after": item.after}


def _rollback(item: Publication) -> None:
    """Restore only still-owned replacement bytes; never erase a racing writer."""
    errors = []
    for name, new_hash in item.after.items():
        destination, previous = item.root / name, item.before[name]
        current = optional_hash(destination)
        if current == previous:
            continue
        if current != new_hash:
            errors.append(name)
            continue
        if previous is None:
            destination.unlink()
        else:
            copy_verified(item.directory / "old" / name, destination, previous)
    if errors:
        raise RuntimeError("source-float rollback blocked by changed outputs: " + ", ".join(errors))


def publish_files(root: Path, entries: dict[str, tuple[Path, str]],
                  before: dict[str, str | None], guard: Callable[[], None]) -> None:
    """Publish prepared files in caller order, rolling back ordinary exceptions."""
    item = _prepare(root, entries, before)
    guard()
    marker = root / PENDING_PUBLICATION
    write_new(item.directory / "intent.json", _journal(item))
    write_new(marker, _journal(item))
    try:
        last_name = next(reversed(item.after))
        for name, expected in item.after.items():
            if name == last_name:
                guard()
            if optional_hash(root / name) != item.before[name]:
                raise RuntimeError("source-float output raced before its replacement")
            if file_hash(item.directory / "new" / name) != expected:
                raise RuntimeError("source-float staged publication bytes changed")
            os.replace(item.directory / "new" / name, root / name)
        guard()
        marker.unlink()
    except (OSError, RuntimeError, ValueError):
        _rollback(item)
        marker.unlink()
        raise
