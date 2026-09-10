"""Current pinned code/tool closure for private opening execution, not approval."""
from __future__ import annotations

import shutil
import hashlib
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash, read_bytes, real_directory
from guided_opening_inputs import OpeningInputs, closed, hash_value
from render_effect_discovery import local_python_import_closure
from guided_proposal_reframe import V6_SCHEMA, V7_SCHEMA
from guided_proposal_presenter_frames import V8_SCHEMA


def _files(lock: dict, snapshot: Path) -> dict[str, str]:
    """Reobserve all exact pinned files, rejecting aliases, duplicate rows and drift."""
    rows = lock.get("files")
    if type(rows) is not list or not 1 <= len(rows) <= 20000:
        raise RuntimeError("opening pinned pipeline file inventory is invalid")
    expected, sizes, total = {}, {}, 0
    for row in rows:
        closed(row, {"path", "hash"}, "pinned file")
        logical = row["path"]
        if type(logical) is not str or not logical or "\\" in logical or logical.startswith("/") \
                or any(part in {"", ".", ".."} for part in logical.split("/")) or logical in expected:
            raise RuntimeError("opening pinned file path is unsafe or duplicated")
        expected[logical] = hash_value(row["hash"])
        info = (snapshot / logical).lstat()
        sizes[logical] = info.st_size
        total += info.st_size
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 64 * 1024 * 1024 \
                or total > 512 * 1024 * 1024:
            raise RuntimeError("opening pinned source inventory exceeds its bounded regular-file closure")
    if rows != sorted(rows, key=lambda row: row["path"]) or digest(rows) != lock["digest"]:
        raise RuntimeError("opening pinned file inventory digest changed")
    for logical, sha256 in expected.items():
        if file_hash(snapshot / logical, sizes[logical]) != sha256:
            raise RuntimeError(f"opening pinned file bytes changed: {logical}")
    return expected


def _execution_closure(expected: dict[str, str], proposal_version: object = None) -> list[dict]:
    """Actual invoked Python must equal the captured implementation, not today's replacement."""
    producer = Path(__file__).resolve().parent
    root = producer.parents[1]
    paths = local_python_import_closure([producer / "guided_opening_media.py"])
    paths.append(root / "schemas/producer/channel-normalization-receipt-v1.schema.json")
    if type(proposal_version) is int and proposal_version in (6, 7, 8):
        schemas = (V8_SCHEMA, V7_SCHEMA) if proposal_version == 8 else (V7_SCHEMA if proposal_version == 7 else V6_SCHEMA,)
        paths.extend(root / "schemas/producer" / name for name in schemas)
    rows = []
    for path in sorted(set(paths)):
        logical = str(path.relative_to(root))
        observed = file_hash(path)
        if expected.get(logical) != observed:
            raise RuntimeError(f"opening invoked source is absent or changed in pinned closure: {logical}")
        rows.append({"path": logical, "sha256": observed})
    return rows


def _tools() -> dict:
    """Capture actual interpreter/FFmpeg/FFprobe binaries, never command names alone."""
    paths = {"python": str(Path(sys.executable).resolve())}
    for name in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(name)
        if not resolved:
            raise RuntimeError(f"opening is missing required tool: {name}")
        paths[name] = str(Path(resolved).resolve())
    return {name: {"path": path, "sha256": file_hash(Path(path))} for name, path in paths.items()}


def read_closure_refs(lock: dict, executed: dict, capture: Callable[[Path, str], None]) -> tuple[tuple[Path, str], ...]:
    """Bind read-only imports to the original lock without rewriting media history.

    The caller has authenticated the lock and executed inventory. Shared media
    imports are already captured and checked by observe_pipeline. Additional
    read imports are captured before reading; AST parses the SAME authenticated
    bytes, never a temporary replacement whose imports could evade later hashes.
    """
    producer = Path(__file__).resolve().parent
    root = producer.parents[1]
    expected = {row["path"]: hash_value(row["hash"]) for row in lock["files"]}
    media = {row["path"]: row["sha256"] for row in executed["executionClosure"]}
    refs = {}

    def source(path: Path) -> str:
        """Authenticate exactly the bytes used to discover the next imports."""
        logical = str(path.relative_to(root))
        if logical not in expected or logical in media and media[logical] != expected[logical]:
            raise RuntimeError(f"opening read source is absent or changed in pinned closure: {logical}")
        if logical not in media:
            capture(path, expected[logical])
            refs[path] = expected[logical]
        raw = read_bytes(path, 64 * 1024 ** 2)
        if hashlib.sha256(raw).hexdigest() != expected[logical]:
            raise RuntimeError(f"opening read discovery bytes changed from pinned closure: {logical}")
        return raw.decode("utf-8", errors="strict")

    required = [root / logical for logical in expected if logical.startswith("scripts/producer/") and logical.endswith(".py")
                and not {"tests", "__pycache__"}.intersection(Path(logical).parts)]
    local_python_import_closure([producer / "guided_opening_read.py"], source, required)
    return tuple(sorted(refs.items()))


def verify_read_closure(refs: tuple[tuple[Path, str], ...], guard: Callable[[], None]) -> None:
    """Hash only captured read additions under the caller's original finite guard."""
    guard()
    for path, expected in refs:
        guard()
        if file_hash(path, 64 * 1024 ** 2) != expected:
            raise RuntimeError(f"opening read source bytes changed from pinned closure: {path.name}")
        guard()
    guard()


def _pinned_run_id(value: object) -> str:
    """Mirror the writer's ASCII replacement and final 96 UTF-16 units exactly.

    The media authority retains the raw run token; the existing TS pipeline
    writer stores safeRunId(raw). This mapping does not replace the separately
    held lock digest, document identities, or source-file checks.
    """
    if type(value) is not str or not value:
        raise RuntimeError("opening pipeline authority run id is invalid")
    units = value.encode("utf-16-le", errors="surrogatepass")
    result = []
    for index in range(0, len(units), 2):
        char = chr(int.from_bytes(units[index:index + 2], "little"))
        allowed = char.isascii() and (char.isalnum() or char in "._-")
        result.append(char if allowed else "_")
    return "".join(result)[-96:]


def observe_pipeline(inputs: OpeningInputs) -> dict:
    """Validate exact lock/file closure before and after all owned media work."""
    value = closed(inputs.value["pipeline"], {"snapshotRoot", "lockPath", "lockSha256", "digest"}, "pipeline")
    if any(type(value[name]) is not str for name in ("snapshotRoot", "lockPath")):
        raise RuntimeError("opening pipeline paths are malformed")
    root, lock_path = Path(value["snapshotRoot"]), Path(value["lockPath"])
    real_directory(root)
    if root != lock_path.parent / "files" or lock_path.name != "pipeline-lock.json":
        raise RuntimeError("opening pipeline lock does not own its snapshot root")
    lock = bound_json(lock_path, hash_value(value["lockSha256"]))
    closed(lock, {"schemaVersion", "state", "runId", "digest", "files"}, "pipeline lock")
    if type(lock["schemaVersion"]) is not int or lock["schemaVersion"] != 1 or lock["state"] != "pinned" \
            or lock["digest"] != hash_value(value["digest"]) \
            or lock["runId"] != _pinned_run_id(inputs.documents["authority"]["runId"]):
        raise RuntimeError("opening pipeline lock identity is stale")
    files = _files(lock, root)
    proposal = inputs.documents["readinessPacket"].get("proposal", {})
    version = proposal.get("schemaVersion") if type(proposal) is dict else None
    return {"schemaVersion": 1, "kind": "guided-opening-executed-pipeline",
        "pipelineDigest": value["digest"], "lockSha256": value["lockSha256"],
        "pinnedFileCount": len(files), "executionClosure": _execution_closure(files, version), "tools": _tools()}
