"""Content-addressed storage and immutable resolution for scene bundles."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
import unicodedata
from dataclasses import dataclass

from graphics.scene_bundle_manifest import validate_bundle_manifest
from graphics.scene_contract import SceneContractError, canonical_json
from headless.container_io import promote_regular
from headless.safe_source_files import PinnedSourceRoot

_MAX_FILES = 256
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_BUNDLE_BYTES = 128 * 1024 * 1024
_ALLOWED_EXTENSIONS = {
    ".html", ".css", ".js", ".json", ".svg", ".png", ".jpg", ".jpeg",
    ".webp", ".woff", ".woff2", ".ttf", ".otf",
}


@dataclass(frozen=True)
class BundleSnapshot:
    """One verified immutable generation."""

    path: str
    digest: str
    manifest: dict
    files: tuple[dict, ...]


def _canonical_root(path: str, label: str) -> str:
    valid = isinstance(path, str) and os.path.isabs(path) \
        and os.path.normpath(path) == path and os.path.realpath(path) == path
    if not valid or os.path.islink(path) or not os.path.isdir(path):
        raise SceneContractError(f"{label} must be a canonical real directory")
    return path


def _safe_relative(relative: str) -> None:
    valid = relative and "\\" not in relative \
        and unicodedata.normalize("NFC", relative) == relative \
        and not any(ord(char) < 32 for char in relative)
    parts = relative.split("/") if valid else []
    if not valid or any(part in {"", ".", ".."} for part in parts):
        raise SceneContractError(f"unsafe bundle path {relative!r}")
    extension = os.path.splitext(parts[-1])[1].lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise SceneContractError(f"unsupported bundle file {relative!r}")


def _directory_files(
    root: str,
    directory: str,
    names: list[str],
    filenames: list[str],
) -> list[str]:
    for name in names:
        path = os.path.join(directory, name)
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise SceneContractError("bundle directories cannot be symlinks")
    files = []
    for name in filenames:
        path = os.path.join(directory, name)
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        _safe_relative(relative)
        info = os.lstat(path)
        valid = (
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and 0 < info.st_size <= _MAX_FILE_BYTES
        )
        if not valid:
            raise SceneContractError(
                f"bundle member is not one bounded owned file: {relative}")
        files.append(relative)
    return files


def _walk_files(root: str) -> tuple[str, ...]:
    files: list[str] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        files.extend(_directory_files(root, directory, names, filenames))
    ordered = tuple(sorted(files))
    if not ordered or len(ordered) > _MAX_FILES:
        raise SceneContractError("bundle file count is outside the released bound")
    return ordered


def _digest_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256(b"project-sniper-scene-bundle-v1\0")
    for relative, data in sorted(files.items()):
        name = relative.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _manifest(files: dict[str, bytes]) -> dict:
    raw = files.get("bundle.json")
    if raw is None:
        raise SceneContractError("bundle.json is required")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SceneContractError("bundle.json is invalid JSON") from exc
    validated = validate_bundle_manifest(value)
    canonical = canonical_json(validated)
    if raw not in {canonical, canonical + b"\n"}:
        raise SceneContractError("bundle.json must use canonical JSON bytes")
    entries = {validated["fullEntry"], *validated["unitEntries"].values()}
    missing = sorted(entries - set(files))
    if missing:
        raise SceneContractError(f"bundle entry files are missing: {missing}")
    return validated


def capture_bundle(path: str) -> BundleSnapshot:
    """Read one stable attempt/generation and bind every reachable byte."""
    root = _canonical_root(path, "bundle root")
    relative_files = _walk_files(root)
    with PinnedSourceRoot(root) as source:
        files = {relative: source.read(relative) for relative in relative_files}
        source.assert_current()
    total = sum(len(data) for data in files.values())
    if total > _MAX_BUNDLE_BYTES:
        raise SceneContractError("bundle exceeds the 128 MiB released bound")
    manifest = _manifest(files)
    rows = tuple({
        "path": relative, "sizeBytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    } for relative, data in sorted(files.items()))
    return BundleSnapshot(root, _digest_files(files), manifest, rows)


def _generation_path(store_root: str, bundle_id: str, digest: str) -> str:
    if "/" in bundle_id or len(digest) != 64:
        raise SceneContractError("bundle generation identity is invalid")
    return os.path.join(store_root, bundle_id, "generations", digest)


def resolve_bundle(store_root: str, bundle_id: str,
                   expected_digest: str) -> BundleSnapshot:
    """Resolve and re-prove the exact generation named by SceneSpecV1."""
    root = _canonical_root(store_root, "scene bundle store")
    path = _generation_path(root, bundle_id, expected_digest)
    snapshot = capture_bundle(path)
    if snapshot.digest != expected_digest:
        raise SceneContractError("scene bundle generation digest mismatch")
    if snapshot.manifest["bundleId"] != bundle_id:
        raise SceneContractError("scene bundle id does not match its generation")
    return snapshot


def _lock(generations: str):
    path = os.path.join(generations, ".bundle.lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or info.st_uid != os.geteuid():
        os.close(fd)
        raise SceneContractError("scene bundle lock is unsafe")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _copy_snapshot(snapshot: BundleSnapshot, stage: str) -> None:
    for row in snapshot.files:
        source = os.path.join(snapshot.path, row["path"])
        target = os.path.join(stage, row["path"])
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        promote_regular(source, target, row["sha256"], row["sizeBytes"])


def _write_current(bundle_root: str, digest: str) -> None:
    temporary = tempfile.NamedTemporaryFile(
        mode="w", encoding="ascii", dir=bundle_root, delete=False,
        prefix=".CURRENT.", suffix=".tmp")
    try:
        with temporary:
            temporary.write(digest + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary.name, os.path.join(bundle_root, "CURRENT"))
        directory_fd = os.open(bundle_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary.name):
            os.remove(temporary.name)


def promote_bundle(attempt_dir: str, store_root: str,
                   select_current: bool = True) -> BundleSnapshot:
    """Publish an attempt as one content-addressed immutable generation."""
    attempt = capture_bundle(attempt_dir)
    root = _canonical_root(store_root, "scene bundle store")
    bundle_root = os.path.join(root, attempt.manifest["bundleId"])
    generations = os.path.join(bundle_root, "generations")
    os.makedirs(generations, mode=0o700, exist_ok=True)
    fd = _lock(generations)
    stage = tempfile.mkdtemp(prefix=".candidate-", dir=generations)
    target = _generation_path(root, attempt.manifest["bundleId"], attempt.digest)
    try:
        _copy_snapshot(attempt, stage)
        staged = capture_bundle(stage)
        if staged.digest != attempt.digest:
            raise SceneContractError("staged bundle changed during promotion")
        if os.path.lexists(target):
            existing = resolve_bundle(root, attempt.manifest["bundleId"],
                                      attempt.digest)
            shutil.rmtree(stage)
            stage = ""
            result = existing
        else:
            os.rename(stage, target)
            stage = ""
            result = resolve_bundle(root, attempt.manifest["bundleId"],
                                    attempt.digest)
        if select_current:
            _write_current(bundle_root, attempt.digest)
        return result
    finally:
        if stage and os.path.isdir(stage):
            shutil.rmtree(stage)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
