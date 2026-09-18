"""Closed original caption observations across workers, never live burn authority.

The caller authenticates the actual original result/reference independently.
Decoding even a self-consistent record only reconstructs held observations and
revalidates them; it cannot authorize execution, approval or a skipped burn.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from cut_preview_io import digest
from guided_caption_dependencies import CaptionFile, Guard, MAX_FILES, MAX_FILE_BYTES, read_caption_json
from guided_caption_projection import CaptionProjectionBinding, HeldCaptionProjection, _DOCUMENTS, read_caption_projection

_KIND = "guided-original-caption-projection"
_SCOPE = "actual-return-observation-not-live-completion-or-approval"


def _closed(value: object, keys: set[str], label: str) -> dict:
    """Reject unknown fields instead of treating a newer claim as V1 evidence."""
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError("caption record " + label + " is not its closed contract")
    return value


def _path(value: object) -> str:
    """Canonical lexical absolute path; the strong reader proves no-follow bytes."""
    if type(value) is not str or not 1 <= len(value) <= 4096 or "\\" in value \
            or not value.startswith("/") or str(Path(value)) != value \
            or any(part in {"", ".", ".."} for part in value.split("/")[1:]) \
            or any(ord(char) < 32 for char in value):
        raise RuntimeError("caption record path is malformed")
    return value


def _sha(value: object) -> str:
    """Only exact lowercase SHA-256 metadata is accepted."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError("caption record hash is malformed")
    return value


def _file(value: object) -> CaptionFile:
    """Bound safe cross-runtime sizes; never retain rich nanosecond stat integers."""
    row = _closed(value, {"path", "sha256", "size_bytes"}, "file")
    if type(row["size_bytes"]) is not int or not 0 < row["size_bytes"] <= MAX_FILE_BYTES:
        raise RuntimeError("caption record file size is malformed or unsupported")
    return CaptionFile(_path(row["path"]), _sha(row["sha256"]), row["size_bytes"])


def _files(value: object) -> tuple[CaptionFile, ...]:
    """Retain a complete bounded, duplicate-free inventory before reading any file."""
    if type(value) is not list or not 1 <= len(value) <= MAX_FILES:
        raise RuntimeError("caption record file inventory is malformed")
    rows = tuple(_file(row) for row in value)
    if len({row.path for row in rows}) != len(rows):
        raise RuntimeError("caption record file inventory has duplicate paths")
    return rows


def _binding(value: object) -> CaptionProjectionBinding:
    """Parse retained observations; the caller supplies an independent binding."""
    row = _closed(value, {"plan", "manifest", "timeline", "frame_clock", "dependencies", "execution_input_hash"}, "binding")
    clock = row["frame_clock"]
    if type(clock) is not list or len(clock) != 4 or type(clock[0]) is not str \
            or any(type(item) is not int or not 0 < item <= 2 ** 53 - 1 for item in clock[1:]):
        raise RuntimeError("caption record clock is malformed")
    return CaptionProjectionBinding(_file(row["plan"]), _file(row["manifest"]), _file(row["timeline"]),
        tuple(clock), _files(row["dependencies"]), _sha(row["execution_input_hash"]))


def caption_projection_record(held: HeldCaptionProjection) -> dict:
    """Hold original raw documents without reserializing their domain-hashed data.

    Cross-runtime JSON normalizes 255.0 to255; historical caption digests do
    not. Exact raw file references preserve both lexical numeric types and
    original bytes. This record never reseals those caption-domain receipts.
    """
    if type(held) is not HeldCaptionProjection or digest(held.data) != held.data_hash:
        raise RuntimeError("caption projection changed before serialization")
    binding = asdict(held.binding)
    binding["frame_clock"] = list(binding["frame_clock"])
    binding["dependencies"] = list(binding["dependencies"])
    body = {"schemaVersion": 1, "kind": _KIND, "scope": _SCOPE, "root": held.root,
        "binding": binding, "dataHash": held.data_hash,
        "files": [asdict(row) for row in held.files], "external": [asdict(row) for row in held.external]}
    return {**body, "recordHash": digest(body)}


def read_caption_record(value: object, binding: CaptionProjectionBinding,
                        root: Path, guard: Guard) -> HeldCaptionProjection:
    """Reconstruct only this original root/binding and strongly re-read its bytes."""
    guard()
    row = _closed(value, {"schemaVersion", "kind", "scope", "root", "binding", "dataHash",
                          "files", "external", "recordHash"}, "observation")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 or row["kind"] != _KIND \
            or row["scope"] != _SCOPE or _path(row["root"]) != str(root):
        raise RuntimeError("caption record identity/root differs")
    if digest({key: item for key, item in row.items() if key != "recordHash"}) != _sha(row["recordHash"]):
        raise RuntimeError("caption record bytes differ from their retained identity")
    original = _binding(row["binding"])
    if original != binding:
        raise RuntimeError("caption record is not the independently held original binding")
    files = _files(row["files"])
    data = _original_documents(files, root, guard)
    held = HeldCaptionProjection(str(root), original, data, _sha(row["dataHash"]), files, _files(row["external"]))
    return read_caption_projection(held, binding, guard)


def _original_documents(files: tuple[CaptionFile, ...], root: Path, guard: Guard) -> dict:
    """Read fixed-role original raw files, not values copied into another JSON."""
    inventory = {row.path: row for row in files}
    paths = {role: str(root / name) for role, name in _DOCUMENTS.items()}
    if not set(paths.values()).issubset(inventory):
        raise RuntimeError("caption record omitted an original fixed-role document")
    return {role: read_caption_json(inventory[path], guard) for role, path in paths.items()}
