"""Original recorded worker inventory joins, not today's execution discovery.

The enclosing stopped-media reader authenticates and verifies the original
pipeline snapshot/lock and actual executed-pipeline record. These subset checks
do NOT rediscover a complete historical closure or grant executable authority.
Only original pinned worker/approval bytes are read by the enclosing reader.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from color.grade_contract import closed
from cut_preview_io import digest
from guided_opening_pipeline import _pinned_run_id
from guided_source_color_staging_contract import _hash, _literal, _path
from headless.external_media_probe_policy import MediaProbeLimits, NODE_PROBE, container_command

PREFIX = "scripts/producer/"
WORKER = PREFIX + "headless/grade_observation_worker.js"
APPROVAL = PREFIX + "headless/render_image_approval.json"
EXECUTION_ROOTS = (WORKER, APPROVAL, PREFIX + "headless/grade_observation_policy.py",
                   PREFIX + "color/grade_frame_adapter.py", PREFIX + "color/grade_observation_read.py")
PROJECT_ROOTS = (*EXECUTION_ROOTS, PREFIX + "color/grade_project.py", PREFIX + "color/grade_project_owned.py")
STAGED_ROOTS = (*PROJECT_ROOTS, PREFIX + "color/grade_project_input.py", PREFIX + "color/grade_project_worker.py")


def pipeline_inventory(inputs: object, implementation: dict) -> dict[str, str]:
    """Join authenticated original lock and executed rows without current code/tool IO."""
    closed(implementation, {"pipelineLock", "executedPipeline", "imageApproval"}, "cold implementation")
    value = closed(inputs.value["pipeline"], {"snapshotRoot", "lockPath", "lockSha256", "digest"}, "cold pipeline")
    root, lock_path = _path(value["snapshotRoot"]), _path(value["lockPath"])
    if root != lock_path.parent / "files" or lock_path.name != "pipeline-lock.json":
        raise ValueError("cold pipeline snapshot namespace differs")
    lock = closed(implementation["pipelineLock"], {"schemaVersion", "state", "runId", "digest", "files"}, "cold lock")
    _literal(lock, {"schemaVersion": 1, "state": "pinned", "digest": _hash(value["digest"]),
                   "runId": _pinned_run_id(inputs.documents["authority"]["runId"])})
    expected = _lock_rows(lock["files"])
    if digest(lock["files"]) != lock["digest"]:
        raise ValueError("cold pipeline original inventory digest differs")
    actual = closed(implementation["executedPipeline"], {"schemaVersion", "kind", "pipelineDigest", "lockSha256",
                    "pinnedFileCount", "executionClosure", "tools"}, "cold executed pipeline")
    _literal(actual, {"schemaVersion": 1, "kind": "guided-opening-executed-pipeline", "pipelineDigest": lock["digest"],
                     "lockSha256": _hash(value["lockSha256"]), "pinnedFileCount": len(expected)})
    logical_inventory(actual["executionClosure"], expected, (PREFIX + "guided_opening_media.py",))
    tools = closed(actual["tools"], {"python", "ffmpeg", "ffprobe"}, "cold original tools")
    for row in tools.values():
        closed(row, {"path", "sha256"}, "cold original tool")
        _path(row["path"])
        _hash(row["sha256"])
    return {str(root / logical): sha for logical, sha in expected.items()}


def _lock_rows(rows: object) -> dict[str, str]:
    """Keep exact sorted relative names and original hashes, without opening them."""
    if type(rows) is not list or not 1 <= len(rows) <= 20000:
        raise ValueError("cold original pipeline inventory is unbounded")
    result = {}
    for row in rows:
        closed(row, {"path", "hash"}, "cold pinned row")
        name = row["path"]
        if type(name) is not str or not name or name.startswith("/") or "\\" in name or any(ord(char) < 32 for char in name) \
                or any(part in ("", ".", "..") for part in name.split("/")) or name in result:
            raise ValueError("cold original pipeline logical name is unsafe or repeated")
        result[name] = _hash(row["hash"])
    if list(result) != sorted(result):
        raise ValueError("cold original pipeline inventory order differs")
    return result


def logical_inventory(rows: object, expected: dict, roots: tuple) -> dict:
    """Validate a recorded subset with required roots, never a newly discovered closure."""
    if type(rows) is not list or not 1 <= len(rows) <= 4000:
        raise ValueError("cold recorded worker inventory is unbounded")
    result = {}
    for row in rows:
        closed(row, {"path", "sha256"}, "cold worker inventory row")
        path = row["path"]
        if type(path) is not str or path in result or expected.get(path) != _hash(row["sha256"]):
            raise ValueError("cold recorded worker inventory escaped original pinned hashes")
        result[path] = row["sha256"]
    if list(result) != sorted(result) or not set(roots) <= set(result):
        raise ValueError("cold recorded worker inventory omitted indispensable original roots")
    return result


def recorded_inventory(rows: object, pins: dict, roots: tuple) -> dict:
    """Require exact original snapshot paths for staged/project/worker attestations."""
    expected, root = pins["expected"], Path(pins["snapshot"])
    return logical_inventory(rows, expected, tuple(str(root / name) for name in roots))


@dataclass(frozen=True)
class _CommandFields:
    """Inert historical argv fields only; not DockerRuntime or a live launch owner."""

    docker: str
    socket: str
    image_id: str
    user_id: str


def recorded_command_hash(claim: dict, request: dict, worker: str) -> str:
    """Reuse the original pure command builder; never execute or resolve current tools."""
    runtime = claim["runtime"]
    fields = _CommandFields(runtime["dockerPath"], runtime["dockerSocketPath"], runtime["imageId"], runtime["userId"])
    original = {key: request[key] for key in ("sourceSha256", "frameCount", "timeoutSeconds")}
    command = container_command(fields, claim["executionDir"], claim["containerName"], claim["sourcePath"], MediaProbeLimits())
    if command.count(NODE_PROBE) != 1:
        raise RuntimeError("cold original grade command compatibility changed")
    return digest(command[:command.index(NODE_PROBE)] + [worker, json.dumps(original)])
