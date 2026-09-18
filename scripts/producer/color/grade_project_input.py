"""Shared exact grade job input and pre-spawn implementation validation.

This is a data reader, not a worker entry, execution capability or admission
check. It preserves the actual original parent PID and explicit profile rules.
The source inventory remains owned by the existing project implementation;
the worker and this extracted reader both require their actual held raw pins.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from color.grade_observation_profile import observation_profile, project_profile
from cut_preview_io import bound_json, file_hash, read_bytes, real_directory

_SHA = re.compile(r"[a-f0-9]{64}")
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")


def _implementation_sha(value: dict) -> str:
    """Never allow the optional-hash reader's None sentinel at this boundary."""
    sha = value.get("implementationSha256") if type(value) is dict else None
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise RuntimeError("project observation implementation hash is invalid")
    return sha


def read_grade_project_input(path: Path, expected: str, profile: str | None = None) -> dict:
    """Only the exact hash held by the spawning owner can name this attempt."""
    raw = read_bytes(path, 128 * 1024)
    if not _SHA.fullmatch(expected) or hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("project observation input differs from live owner")
    value = json.loads(raw.decode("utf8", errors="strict"))
    keys = {"schemaVersion", "policy", "jobId", "producerDir", "sourceId", "declaration",
            "expected", "ownerPid", "implementationSha256"}
    if profile is not None:
        keys.add("profile")
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError("project observation input schema is invalid")
    _implementation_sha(value)
    if project_profile(value) != observation_profile(profile):
        raise RuntimeError("project observation input differs from explicit owner profile")
    if type(value["jobId"]) is not str or not _UUID.fullmatch(value["jobId"]) \
            or type(value["sourceId"]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value["sourceId"]):
        raise RuntimeError("project observation identities are invalid")
    if type(value["ownerPid"]) is not int or os.getppid() != value["ownerPid"]:
        raise RuntimeError("project observation was not launched by its held owner")
    expected_parents = value["expected"]
    if type(expected_parents) is not dict or set(expected_parents) != {"planSha256", "manifestSha256", "projectSha256"} \
            or any(type(item) is not str or not _SHA.fullmatch(item) for item in expected_parents.values()):
        raise RuntimeError("project observation parent hashes are invalid")
    producer = Path(value["producerDir"])
    real_directory(producer)
    if path != producer / ".sniper-grade-observations" / value["jobId"] / "input.json":
        raise RuntimeError("project observation input escaped its owner-derived attempt")
    return value


def verify_grade_project_implementation(directory: Path, value: dict) -> None:
    """Match actual adapter, unchanged worker, and shared reader to owner pins."""
    expected = _implementation_sha(value)
    from color.grade_project import implementation

    inventory = bound_json(directory / "implementation.json", expected)
    rows = inventory.get("files")
    if type(rows) is not list or not 1 <= len(rows) <= 4000:
        raise RuntimeError("project observation implementation inventory is invalid")
    known = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"path", "sha256"} or type(row["path"]) is not str \
                or type(row["sha256"]) is not str or not _SHA.fullmatch(row["sha256"]) or row["path"] in known:
            raise RuntimeError("project observation implementation rows are invalid")
        known[row["path"]] = row["sha256"]
    for row in implementation():
        if known.get(row["path"]) != row["sha256"]:
            raise RuntimeError("project observation code differs from pre-spawn held source bytes")
    entry = Path(__file__).with_name("grade_project_worker.py").resolve()
    if known.get(str(entry)) != file_hash(entry):
        raise RuntimeError("project observation entry is absent from held source bytes")
    reader = Path(__file__).resolve()
    if known.get(str(reader)) != file_hash(reader):
        raise RuntimeError("project observation input reader is absent from held source bytes")
