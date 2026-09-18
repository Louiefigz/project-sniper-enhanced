"""Deterministic sealed inputs and no-follow output promotion."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass

from graphics.composition_transform import set_root_duration
from graphics.template_contract import resolved_assets
from headless.safe_source_files import PinnedSourceRoot
from headless.sealed_archive import verify_archive_file
from headless.sealed_tar_format import canonical_tar_bytes
from headless.source_closure import discover_sources

_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_PROMOTION_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class CompositionInput:
    """Named live source plus the only trusted optional source transform."""

    relative_path: str
    html: str
    render_intent: dict | None = None
    duration: float | None = None


@dataclass(frozen=True)
class SealedInput:
    """One immutable archive and its externally known content manifest."""

    path: str
    sha256: str
    manifest: tuple[dict, ...]
    asset_bindings: tuple[dict, ...] = ()
    size_bytes: int | None = None


def _read_regular(path: str, root: str) -> bytes:
    """Compatibility wrapper around the no-follow pinned-root reader."""
    relative = os.path.relpath(path, root)
    with PinnedSourceRoot(root) as source:
        return source.read(relative)


def _composition_source(composition: CompositionInput,
                        source: PinnedSourceRoot) -> tuple[bytes, bytes]:
    original = source.read(composition.relative_path)
    if original != composition.html.encode("utf-8"):
        raise RuntimeError("sealed composition does not match its named source")
    rendered = (original if composition.duration is None
                else set_root_duration(composition.html, composition.duration).encode())
    return original, rendered


def _local_sources(html: str, source: PinnedSourceRoot) -> dict[str, bytes]:
    return {f"motion/{path}": data
            for path, data in discover_sources(html, source.read).items()}


def _asset_sources(spec: dict, html: str, source: PinnedSourceRoot
                   ) -> tuple[dict[str, bytes], tuple[dict, ...]]:
    sources, bindings = {}, []
    for asset in resolved_assets({"spec": spec}, html):
        path = asset["path"]
        lexical = os.path.join(os.path.realpath(os.path.dirname(path)),
                               os.path.basename(path))
        rel = os.path.relpath(lexical, source.path)
        archive_path = f"motion/{rel}"
        data = source.read(rel)
        sources[archive_path] = data
        bindings.append({
            "field": asset["field"], "selector": asset["selector"],
            "path": archive_path, "sha256": hashlib.sha256(data).hexdigest(),
        })
    ordered = tuple(sorted(bindings, key=lambda row: (row["field"], row["selector"])))
    return sources, ordered


def _assert_source_epoch(source: PinnedSourceRoot,
                         expected: dict[str, bytes]) -> None:
    for name, data in expected.items():
        if source.read(name.removeprefix("motion/")) != data:
            raise RuntimeError("render input closure changed while sealing")


def _source_entries(pipeline: str, composition: CompositionInput,
                    spec: dict) -> tuple[dict[str, bytes], tuple[dict, ...]]:
    motion = os.path.join(os.path.realpath(pipeline), "templates", "motion")
    if os.path.islink(motion):
        raise RuntimeError("motion source root must not be a symlink")
    comp_rel = composition.relative_path
    if os.path.isabs(comp_rel) or ".." in comp_rel.split("/"):
        raise RuntimeError("invalid sealed composition path")
    with PinnedSourceRoot(motion) as source:
        original, rendered = _composition_source(composition, source)
        sources = _local_sources(rendered.decode("utf-8"), source)
        assets, bindings = _asset_sources(spec, composition.html, source)
        sources.update(assets)
        entries = dict(sources)
        entries[f"motion/{comp_rel}"] = rendered
        expected = {**sources, f"motion/{comp_rel}": original}
        _assert_source_epoch(source, expected)
        source.assert_current()
    return entries, bindings


def _manifest(entries: dict[str, bytes]) -> tuple[dict, ...]:
    return tuple({"path": path, "sizeBytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}
                 for path, data in sorted(entries.items()))


def _write_snapshot(fd: int, entries: dict[str, bytes]) -> str:
    encoded = canonical_tar_bytes(entries)
    if len(encoded) > _MAX_ARCHIVE_BYTES:
        raise RuntimeError("sealed render input exceeds 128 MiB")
    with os.fdopen(fd, "wb") as raw:
        raw.write(encoded)
        raw.flush()
        os.fsync(raw.fileno())
    return hashlib.sha256(encoded).hexdigest()


def _frozen_json(value: object, expected: type, label: str):
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
        frozen = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"sealed render {label} is not canonical JSON") from exc
    if type(frozen) is not expected:
        raise RuntimeError(f"sealed render {label} has the wrong type")
    return frozen


def create_snapshot(pipeline: str, composition: CompositionInput,
                    spec: dict, directory: str) -> SealedInput:
    """Copy only declared render inputs into one hash-checked regular tar."""
    frozen_spec = _frozen_json(spec, dict, "variables")
    frozen_intent = (None if composition.render_intent is None else
                     _frozen_json(composition.render_intent, dict, "intent"))
    entries, asset_bindings = _source_entries(
        pipeline, composition, frozen_spec)
    variables = json.dumps(frozen_spec, ensure_ascii=True, separators=(",", ":"),
                           sort_keys=True, allow_nan=False).encode("utf-8")
    entries["request/variables.json"] = variables
    bindings = json.dumps(asset_bindings, ensure_ascii=True, separators=(",", ":"),
                          sort_keys=True, allow_nan=False).encode("utf-8")
    entries["request/asset-bindings.json"] = bindings
    if frozen_intent is not None:
        intent = json.dumps(frozen_intent, ensure_ascii=True,
                            separators=(",", ":"), sort_keys=True,
                            allow_nan=False).encode("utf-8")
        entries["request/render-intent.json"] = intent
    manifest = _manifest(entries)
    manifest_bytes = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"),
                                sort_keys=True).encode("utf-8")
    entries["request/input-manifest.json"] = manifest_bytes
    path = os.path.join(directory, "render-input.tar")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o400)
    try:
        os.fchmod(fd, 0o400)
        transferred, fd = fd, -1
        digest = _write_snapshot(transferred, entries)
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        proof = verify_archive_file(path, digest, manifest)
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return SealedInput(
        path, digest, manifest, asset_bindings, proof["sizeBytes"])


def verify_snapshot_archive(path: str, expected_sha256: str,
                            manifest: tuple[dict, ...]) -> dict:
    """Revalidate the retained tar digest, inode, and exact member closure."""
    return verify_archive_file(path, expected_sha256, manifest)


def _source_fd(path: str,
               expected_size: int | None = None) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    info = os.fstat(fd)
    size_ok = (0 < info.st_size <= _MAX_PROMOTION_BYTES
               and (expected_size is None or info.st_size == expected_size))
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or not size_ok):
        os.close(fd)
        raise RuntimeError(
            "staged render must be one bounded regular file of the expected size")
    return fd, info


def _write_chunk(destination_fd: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        written = os.write(destination_fd, view)
        if written <= 0:
            raise RuntimeError("staged render promotion made no progress")
        view = view[written:]


def _copy_fd(source_fd: int, destination_fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)
        _write_chunk(destination_fd, chunk)


def _cleanup_promotion(source_fd: int, destination_fd: int,
                       directory_fd: int, temp_name: str) -> None:
    os.close(source_fd)
    if destination_fd >= 0:
        os.close(destination_fd)
    if directory_fd < 0:
        return
    try:
        os.unlink(temp_name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)


def promote_regular(staged: str, output: str,
                    expected_sha256: str | None = None,
                    expected_size: int | None = None) -> None:
    """Promote a held regular inode without following source or target links."""
    if expected_size is not None and (
            type(expected_size) is not int or expected_size <= 0
            or expected_size > _MAX_PROMOTION_BYTES):
        raise RuntimeError("expected promotion size is invalid")
    source_fd, before = _source_fd(staged, expected_size)
    out_dir, basename = os.path.dirname(output), os.path.basename(output)
    if not basename or basename in {".", ".."}:
        os.close(source_fd)
        raise RuntimeError("render cache destination is invalid")
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    temp_name = f".{basename}.{uuid.uuid4().hex}.promote"
    directory_fd = destination_fd = -1
    try:
        directory_fd = os.open(out_dir, dir_flags)
        create_flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0))
        destination_fd = os.open(temp_name, create_flags, 0o600, dir_fd=directory_fd)
        os.fchmod(destination_fd, 0o600)
        copied_sha256 = _copy_fd(source_fd, destination_fd)
        after = os.fstat(source_fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                before.st_nlink) != (after.st_dev, after.st_ino, after.st_size,
                                     after.st_mtime_ns, after.st_nlink):
            raise RuntimeError("staged render changed during promotion")
        if expected_sha256 is not None and copied_sha256 != expected_sha256:
            raise RuntimeError("staged render does not match its media proof")
        os.fsync(destination_fd)
        os.close(destination_fd)
        destination_fd = -1
        try:
            os.link(temp_name, basename, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False)
        except FileExistsError as exc:
            raise RuntimeError("render cache destination already exists") from exc
        os.unlink(temp_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        _cleanup_promotion(source_fd, destination_fd, directory_fd, temp_name)
