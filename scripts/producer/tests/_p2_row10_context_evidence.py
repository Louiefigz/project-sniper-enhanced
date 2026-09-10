"""Materialized non-claim preconditions for the row-10 lifecycle fixture."""
from __future__ import annotations

import os
from pathlib import Path

from edit.cut_repair_context_sources import canonical_bytes
from fingerprints import file_sha256


def _evidence_file(root: str, name: str, value: object) -> dict:
    path = os.path.join(root, name)
    if isinstance(value, bytes):
        Path(path).write_bytes(value)
    else:
        Path(path).write_bytes(canonical_bytes(value))
    return {"path": path, "sha256": file_sha256(path)}


def materialize_context_evidence(
    producer: str,
    source: str,
    parent: str,
    target: dict,
) -> dict[str, dict]:
    """Back every syntactic context hash with controlled fixture bytes."""
    root = os.path.join(producer, "row10-context-evidence")
    os.makedirs(root)
    values = {
        "alignment": {
            "kind": "controlled-alignment-precondition",
            "sourceSha256": file_sha256(source),
            "target": target,
        },
        "runtime": b"row10 controlled alignment runtime v1",
        "model": b"row10 controlled alignment model v1",
        "cache": {"target": target, "occurrences": [0.4, 2.0]},
        "vad": {
            "kind": "controlled-vad-precondition",
            "parentSha256": file_sha256(parent),
        },
        "audition": {
            "kind": "controlled-operator-damage-report",
            "damage": "later take omitted at the seg-b start edge",
        },
        "isolation": {
            "kind": "controlled-dialogue-isolation-precondition",
            "musicSfxOverlapCount": 0,
        },
        "isolationRuntime": b"row10 controlled isolation runtime v1",
        "replaceableAudio": {
            "kind": "replaceable-audio-ranges", "ranges": [],
        },
    }
    return {
        name: _evidence_file(root, f"{name}.evidence", value)
        for name, value in values.items()
    }
