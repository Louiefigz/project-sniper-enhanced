"""Crash-aware publication for qualified-media plan rebind artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from qualification_mezzanine_files import regular_directory


@dataclass(frozen=True)
class _Stage:
    """One fsynced staged file and its intended final name."""

    temporary: Path
    final: Path
    device: int
    inode: int


@dataclass(frozen=True)
class RebindPublication:
    """Plan, support evidence, and their three new final paths."""

    output: Path
    plan: dict
    proposal_output: Path
    proposal: dict
    report: Path
    result: dict


def _payload(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def _stage(path: Path, payload: bytes) -> _Stage:
    regular_directory(path.parent, "rebind output")
    if path.suffix.lower() != ".json" or os.path.lexists(path):
        raise RuntimeError("rebind outputs must be new JSON files")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o400)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("rebind stage is not one regular file")
        return _Stage(Path(temporary), path, info.st_dev, info.st_ino)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise


def _unlink_owned(stage: _Stage) -> None:
    try:
        current = os.lstat(stage.final)
    except FileNotFoundError:
        return
    if (current.st_dev, current.st_ino) != (stage.device, stage.inode):
        raise RuntimeError("refusing to roll back a changed rebind output")
    os.unlink(stage.final)


def _cleanup(stages: list[_Stage]) -> None:
    for stage in stages:
        try:
            current = os.lstat(stage.temporary)
        except FileNotFoundError:
            continue
        if (current.st_dev, current.st_ino) != (stage.device, stage.inode):
            raise RuntimeError("refusing to remove a changed rebind stage")
        os.unlink(stage.temporary)


def _sync_parents(stages: list[_Stage]) -> None:
    for parent in {stage.final.parent for stage in stages}:
        descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _commit(stages: list[_Stage]) -> None:
    published: list[_Stage] = []
    try:
        for stage in stages:
            os.link(stage.temporary, stage.final, follow_symlinks=False)
            published.append(stage)
        _sync_parents(stages)
        _cleanup(stages)
        _sync_parents(stages)
    except BaseException:
        rollback_errors = []
        for stage in reversed(published):
            try:
                _unlink_owned(stage)
            except BaseException as exc:
                rollback_errors.append(exc)
        try:
            _cleanup(stages)
            _sync_parents(stages)
        except BaseException as exc:
            rollback_errors.append(exc)
        if rollback_errors:
            raise RuntimeError("rebind publication rollback was incomplete") \
                from rollback_errors[0]
        raise


def publish_bundle(publication: RebindPublication) -> dict:
    """Publish support evidence first and the authoritative plan last."""
    paths = [
        Path(os.path.abspath(publication.proposal_output)),
        Path(os.path.abspath(publication.report)),
        Path(os.path.abspath(publication.output)),
    ]
    if len(set(paths)) != 3:
        raise RuntimeError("rebind output paths must be distinct")
    plan_bytes = _payload(publication.plan)
    proposal_bytes = _payload(publication.proposal)
    completed = {
        **publication.result,
        "planSha256": hashlib.sha256(plan_bytes).hexdigest(),
        "proposalSha256": hashlib.sha256(proposal_bytes).hexdigest(),
        "publication": {
            "policy": "support-evidence-first-authoritative-plan-last-v1",
            "authoritativePlanPublishedLast": True,
        },
    }
    values = (proposal_bytes, _payload(completed), plan_bytes)
    stages: list[_Stage] = []
    try:
        for path, payload in zip(paths, values):
            stages.append(_stage(path, payload))
    except BaseException:
        _cleanup(stages)
        raise
    _commit(stages)
    return completed
