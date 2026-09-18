"""Deterministic archive assembly and the external integrity records.

Two builds from identical staged inputs produce identical bytes: entries are
sorted, timestamps are fixed, modes are normalised to two values and no symlink
or directory entry is written. The archive's own SHA-256 is computed only after
assembly and is stored outside the archive.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_UNIX_FILE = 0o100644 << 16
_UNIX_EXEC = 0o100755 << 16
_COMPRESS_LEVEL = 9


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, streamed so large media never loads into memory."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _executable(path: Path) -> bool:
    """Whether this staged file should be extracted executable."""
    return path.suffix in {".sh", ".command"} or bool(path.stat().st_mode & 0o100)


def file_manifest(stage: Path) -> list[dict[str, object]]:
    """Sorted per-file manifest of the staged tree.

    Args:
        stage: Staging root.

    Returns:
        One record per file with its archive path, size and SHA-256, sorted by
        path so two builds can be compared directly.
    """
    records: list[dict[str, object]] = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        relative = path.relative_to(stage).as_posix()
        records.append({"path": relative, "bytes": path.stat().st_size,
                        "sha256": file_sha256(path)})
    return records


def write_archive(stage: Path, top_level: str, target: Path) -> None:
    """Assemble the archive deterministically from the staged tree.

    Args:
        stage: Staging root; every regular file under it is archived.
        top_level: Single top-level folder name inside the archive.
        target: Archive path to write.
    """
    files = sorted(p for p in stage.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=_COMPRESS_LEVEL) as bundle:
        for path in files:
            name = f"{top_level}/{path.relative_to(stage).as_posix()}"
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = _UNIX_EXEC if _executable(path) else _UNIX_FILE
            bundle.writestr(info, path.read_bytes())


def external_records(archive: Path, version: str, manifest: list[dict[str, object]],
                     extra: dict[str, object]) -> dict[str, object]:
    """Build the external release manifest for the assembled archive.

    Args:
        archive: The assembled archive.
        version: Release version string.
        manifest: Per-file manifest from `file_manifest`.
        extra: Additional recorded facts (source commit, components, status).

    Returns:
        The external manifest mapping, which deliberately lives outside the
        archive because it carries the archive's own hash.
    """
    return {
        "archive": archive.name,
        "version": version,
        "bytes": archive.stat().st_size,
        "sha256": file_sha256(archive),
        "entries": len(manifest),
        "payload_bytes": sum(int(row["bytes"]) for row in manifest),
        **extra,
    }


def write_checksums(archive: Path, target: Path) -> None:
    """Write a `shasum -a 256 -c`-compatible checksum file beside the archive."""
    target.write_text(f"{file_sha256(archive)}  {archive.name}\n", encoding="utf-8")


def write_json(target: Path, payload: object) -> None:
    """Write sorted, newline-terminated JSON so two builds compare byte-for-byte."""
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
