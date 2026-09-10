"""Hash-bound thumbnail, cover, and loop-frame deliverables."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass

from graphics.render_tools import resolve_tools
from headless.container_io import promote_regular
from headless.docker_identity import file_sha256

_SHA256 = re.compile(r"[0-9a-f]{64}")
_KINDS = {"thumbnail", "cover", "loop-frame"}


class DeliverableError(RuntimeError):
    """A publication image cannot be bound to its approved source."""


@dataclass(frozen=True)
class DeliverableRequest:
    """One exact source-frame extraction request."""

    kind: str
    source_path: str
    source_sha256: str
    sandbox_receipt_hash: str
    frame_index: int
    output_path: str


def _canonical_path(path: str, label: str, must_exist: bool) -> str:
    valid = isinstance(path, str) and os.path.isabs(path) \
        and os.path.normpath(path) == path and os.path.realpath(path) == path
    if not valid or (must_exist and not os.path.isfile(path)):
        raise DeliverableError(f"{label} must be a canonical absolute file")
    if not must_exist and (
            os.path.lexists(path) or not os.path.isdir(os.path.dirname(path))):
        raise DeliverableError(f"{label} must be a new file in a real directory")
    return path


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(request: DeliverableRequest) -> tuple[str, str]:
    if request.kind not in _KINDS:
        raise DeliverableError("deliverable kind is unsupported")
    if type(request.frame_index) is not int or request.frame_index < 0:
        raise DeliverableError("deliverable frame index must be nonnegative")
    for value, label in (
            (request.source_sha256, "source"),
            (request.sandbox_receipt_hash, "sandbox receipt")):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise DeliverableError(f"{label} hash is invalid")
    source = _canonical_path(request.source_path, "source path", True)
    output = _canonical_path(request.output_path, "output path", False)
    if os.path.splitext(output)[1].lower() != ".png":
        raise DeliverableError("frame deliverables must use .png")
    return source, output


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=60,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                 "PATH": "/usr/bin:/bin", "TZ": "UTC"})
    except subprocess.TimeoutExpired as exc:
        raise DeliverableError("deliverable extraction timed out") from exc
    if result.returncode:
        raise DeliverableError(
            f"deliverable extraction failed: {result.stderr.strip()[-240:]}")
    return result


def _extract(source: str, target: str, frame: int, ffmpeg: str) -> None:
    select = f"select=eq(n\\,{frame})"
    _run([
        ffmpeg, "-nostdin", "-v", "error", "-i", source, "-map", "0:v:0",
        "-vf", select, "-frames:v", "1", "-fps_mode", "passthrough",
        "-compression_level", "6", target,
    ])
    if not os.path.isfile(target) or os.path.getsize(target) <= 8:
        raise DeliverableError("requested frame does not exist in source")
    with open(target, "rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise DeliverableError("deliverable encoder did not produce PNG")


def _dimensions(path: str, ffprobe: str) -> tuple[int, int]:
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", path,
    ])
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeliverableError("deliverable dimensions are unproved") from exc
    if width <= 0 or height <= 0:
        raise DeliverableError("deliverable dimensions are invalid")
    return width, height


def _write_receipt(path: str, value: dict) -> None:
    directory = os.path.dirname(path)
    with tempfile.TemporaryDirectory(
            prefix=".deliverable-receipt-", dir=directory) as stage:
        candidate = os.path.join(stage, "receipt.json")
        with open(candidate, "x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        promote_regular(candidate, path)


def create_frame_deliverable(request: DeliverableRequest) -> dict:
    """Extract one real source frame and bind output/tool/sandbox identities."""
    source, output = _validate(request)
    tools = resolve_tools()
    ffmpeg, ffprobe = tools["ffmpeg"], tools["ffprobe"]
    with tempfile.TemporaryDirectory(
            prefix=".deliverable-", dir=os.path.dirname(output)) as stage:
        snapshot = os.path.join(stage, "source.snapshot")
        promote_regular(source, snapshot, request.source_sha256)
        candidate = os.path.join(stage, "frame.png")
        _extract(snapshot, candidate, request.frame_index, ffmpeg)
        digest = _sha256(candidate)
        width, height = _dimensions(candidate, ffprobe)
        promote_regular(candidate, output, digest)
    receipt = {
        "schemaVersion": 1, "kind": request.kind,
        "sourceSha256": request.source_sha256,
        "sandboxReceiptHash": request.sandbox_receipt_hash,
        "frameIndex": request.frame_index,
        "output": {
            "path": output, "sha256": digest, "mime": "image/png",
            "width": width, "height": height,
        },
        "tools": {
            "ffmpegSha256": file_sha256(ffmpeg),
            "ffprobeSha256": file_sha256(ffprobe),
        },
    }
    _write_receipt(output + ".receipt.json", receipt)
    return receipt
