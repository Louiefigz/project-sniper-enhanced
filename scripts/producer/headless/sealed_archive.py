"""Strict validation for retained deterministic render-input archives."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
import unicodedata

from .sealed_tar_format import canonical_tar_bytes

_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MANIFEST_NAME = "request/input-manifest.json"
_REQUIRED = {
    "motion/hyperframes.json", "motion/index.html", "motion/package.json",
    "request/asset-bindings.json", "request/variables.json",
}


def _safe_path(path: object) -> bool:
    if not isinstance(path, str) or not path or unicodedata.normalize("NFC", path) != path:
        return False
    if any(ord(char) < 32 for char in path) or "\\" in path:
        return False
    parts = path.split("/")
    return (parts[0] in {"motion", "request"}
            and all(part not in {"", ".", ".."} for part in parts))


def validate_manifest(manifest: tuple[dict, ...]) -> None:
    """Reject noncanonical rows, aliases, reserved names, and missing roots."""
    if not isinstance(manifest, tuple):
        raise RuntimeError("sealed render manifest must be an immutable tuple")
    paths = []
    for row in manifest:
        valid = (isinstance(row, dict)
                 and set(row) == {"path", "sha256", "sizeBytes"}
                 and _safe_path(row.get("path"))
                 and type(row.get("sizeBytes")) is int
                 and row["sizeBytes"] >= 0
                 and _DIGEST.fullmatch(str(row.get("sha256", ""))))
        if not valid or row["path"] == _MANIFEST_NAME:
            raise RuntimeError("sealed render manifest row is invalid")
        paths.append(row["path"])
    aliases = {path.casefold() for path in paths}
    compositions = [path for path in paths
                    if path.startswith("motion/compositions/") and path.endswith(".html")]
    total = sum(row["sizeBytes"] for row in manifest)
    if (paths != sorted(paths) or len(set(paths)) != len(paths)
            or len(aliases) != len(paths) or not _REQUIRED.issubset(paths)
            or len(compositions) != 1 or total > _MAX_ARCHIVE_BYTES
            or any(row["sizeBytes"] > _MAX_ARCHIVE_BYTES for row in manifest)):
        raise RuntimeError("sealed render manifest closure is invalid")


def _manifest_bytes(manifest: tuple[dict, ...]) -> bytes:
    return json.dumps(manifest, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def _expected_rows(manifest: tuple[dict, ...]) -> dict[str, dict]:
    expected = {row["path"]: row for row in manifest}
    encoded = _manifest_bytes(manifest)
    expected[_MANIFEST_NAME] = {
        "path": _MANIFEST_NAME, "sizeBytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    return expected


def _canonical_member(member: tarfile.TarInfo) -> bool:
    return (member.type == tarfile.REGTYPE and not member.pax_headers
            and member.mode == 0o444 and member.mtime == 0
            and member.uid == 0 and member.gid == 0
            and member.uname == "" and member.gname == ""
            and _safe_path(member.name))


def _verified_member(archive: tarfile.TarFile, member: tarfile.TarInfo,
                     expected: dict[str, dict]) -> bytes:
    extracted = archive.extractfile(member)
    if extracted is None:
        raise RuntimeError("sealed render archive member is unreadable")
    data = extracted.read()
    row = expected[member.name]
    if (len(data) != row["sizeBytes"]
            or hashlib.sha256(data).hexdigest() != row["sha256"]):
        raise RuntimeError(f"sealed render archive member mismatch: {member.name}")
    return data


def _canonical_json(data: bytes, expected_type: type, label: str) -> None:
    try:
        value = json.loads(data)
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False).encode("ascii")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"sealed render {label} is invalid JSON") from exc
    if type(value) is not expected_type or data != encoded:
        raise RuntimeError(f"sealed render {label} is not canonical JSON")


def _validate_request_json(entries: dict[str, bytes]) -> None:
    _canonical_json(entries["request/variables.json"], dict, "variables")
    _canonical_json(entries["request/asset-bindings.json"], list, "asset bindings")
    intent = entries.get("request/render-intent.json")
    if intent is not None:
        _canonical_json(intent, dict, "intent")


def _verify_members(data: bytes, manifest: tuple[dict, ...]) -> tuple[str, ...]:
    validate_manifest(manifest)
    expected = _expected_rows(manifest)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        valid = (names == sorted(names) and len(names) == len(set(names))
                 and set(names) == set(expected)
                 and not archive.pax_headers
                 and all(_canonical_member(member) for member in members))
        if not valid:
            raise RuntimeError("sealed render archive member closure is invalid")
        entries = {}
        for member in members:
            entries[member.name] = _verified_member(archive, member, expected)
    _validate_request_json(entries)
    if canonical_tar_bytes(entries) != data:
        raise RuntimeError("sealed render archive is not canonical USTAR")
    return tuple(names)


def _read_all(fd: int) -> bytes:
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def verify_archive_binding(path: str, expected_sha256: str,
                           manifest: tuple[dict, ...]) -> dict:
    """Return proof from the exact held tar inode, including its file mode."""
    if not _DIGEST.fullmatch(str(expected_sha256)):
        raise RuntimeError("retained render archive digest is invalid")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        safe = (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == os.geteuid() and 0 < before.st_size
                <= _MAX_ARCHIVE_BYTES
                and stat.S_IMODE(before.st_mode) in {0o400, 0o600})
        if not safe:
            raise RuntimeError("retained render archive must be one bounded regular file")
        data = _read_all(fd)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise RuntimeError("retained render archive digest mismatch")
        names = _verify_members(data, manifest)
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError("retained render archive changed during proof")
        return {"device": before.st_dev, "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode),
                "sha256": expected_sha256, "sizeBytes": before.st_size,
                "members": names}
    finally:
        os.close(fd)


def verify_archive_file(path: str, expected_sha256: str,
                        manifest: tuple[dict, ...]) -> dict:
    """Revalidate one retained tar through a stable, private regular inode."""
    proof = verify_archive_binding(path, expected_sha256, manifest)
    return {key: proof[key] for key in ("sha256", "sizeBytes", "members")}
