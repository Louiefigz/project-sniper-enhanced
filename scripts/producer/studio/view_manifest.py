"""Generation manifest + view fingerprint for a Studio review project.

``studio.manifest.json`` records the sha256 of every generated file at
generation time. Studio persists user edits by MUTATING project files on
disk, so a directory whose files differ from its manifest carries unsynced
edits — the generator must refuse to overwrite it (``--force`` overrides).
``view.fingerprint.json`` binds the view to its inputs: the canonicalized
graphicsTrack, the base video's file identity, and the generator version.
"""
from __future__ import annotations

import hashlib
import json
import os

from fingerprints import json_canon
from studio import StudioProjectError

LEGACY_GENERATOR_VERSION = "studio-project-v1"
GENERATOR_VERSION = "studio-project-v2"
COMPOSITION_NORMALIZER = "hf-ids-0.8.31"
MANIFEST_NAME = "studio.manifest.json"
FINGERPRINT_NAME = "view.fingerprint.json"
#: Runtime caches the preview server parks inside the project dir (its log
#: dir, thumbnail cache, and waveform cache) — never operator edits.
_IGNORED_DIRS = {".hyperframes", ".thumbnails", ".waveform-cache"}


def file_sha256(path: str) -> str:
    """Streaming sha256 of one file (symlinks hash their target bytes)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generation_fields(version: str) -> dict:
    """Explicit new generation identity; never relabel an original v1 view."""
    if version == LEGACY_GENERATOR_VERSION:
        return {"generator": version}
    if version == GENERATOR_VERSION:
        return {"generator": version, "compositionNormalizer": COMPOSITION_NORMALIZER}
    raise StudioProjectError("unknown Studio generation version")


def generation_version(manifest: dict, fingerprint: dict | None = None) -> str:
    """Reject unknown/mixed normalizer metadata before SDK work or sync writes."""
    version = manifest.get("generator")
    expected = generation_fields(version)
    actual = {key: manifest[key] for key in ("generator", "compositionNormalizer") if key in manifest}
    if actual != expected:
        raise StudioProjectError("Studio generator/normalizer metadata is inconsistent")
    if fingerprint is not None and generation_version(fingerprint) != version:
        raise StudioProjectError("Studio manifest and fingerprint generation versions differ")
    return version


def build_fingerprint(track: list[dict], base_video: str, version: str = GENERATOR_VERSION) -> dict:
    """The view's identity: effective graphicsTrack + base file + generator."""
    canon = json.dumps(json_canon(track), sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"))
    track_sha = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    stat = os.stat(base_video)
    base = {"path": os.path.abspath(base_video), "bytes": stat.st_size,
            "mtimeNs": stat.st_mtime_ns}
    fields = generation_fields(version)
    tag = version if version == LEGACY_GENERATOR_VERSION else version + ":" + COMPOSITION_NORMALIZER
    seed = "\n".join([tag, track_sha,
                      json.dumps(base, sort_keys=True)])
    return {**fields,
            "graphicsTrackSha256": track_sha,
            "base": base,
            "sha256": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


def write_json(path: str, data: dict) -> None:
    """Deterministic JSON sidecar write (stable key order, trailing newline)."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def _project_files(out_dir: str) -> list[str]:
    """Every tracked-relevant file currently in the project directory."""
    found = []
    for root, dirs, names in os.walk(out_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
        for name in names:
            if name == ".DS_Store":
                continue
            rel = os.path.relpath(os.path.join(root, name), out_dir)
            found.append(rel)
    return sorted(found)


def _media_problems(out_dir: str, media: dict) -> list[str]:
    """Identity check for the (unhashed, possibly multi-GB) base media."""
    rel = media.get("rel")
    if not rel:
        return []
    path = os.path.join(out_dir, rel)
    if not os.path.isfile(path):
        return [f"{rel}: missing"]
    if os.path.getsize(path) != media.get("bytes"):
        return [f"{rel}: modified"]
    return []


def unsynced_changes(out_dir: str) -> list[str]:
    """Differences between the directory and its generation manifest.

    Empty means the directory is absent, empty, or byte-identical to what the
    generator wrote — safe to overwrite. Anything else is a potential Studio
    edit that a regeneration would silently discard.
    """
    if not os.path.isdir(out_dir):
        return []
    manifest_path = os.path.join(out_dir, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        present = _project_files(out_dir)
        return [f"no {MANIFEST_NAME} in a non-empty directory"] if present \
            else []
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    fingerprint_path = os.path.join(out_dir, FINGERPRINT_NAME)
    fingerprint = None
    if os.path.isfile(fingerprint_path):
        with open(fingerprint_path, encoding="utf-8") as handle:
            fingerprint = json.load(handle)
    generation_version(manifest, fingerprint)
    tracked: dict[str, str] = manifest.get("files", {})
    problems = []
    for rel, digest in sorted(tracked.items()):
        path = os.path.join(out_dir, rel)
        if not os.path.isfile(path):
            problems.append(f"{rel}: missing")
        elif file_sha256(path) != digest:
            problems.append(f"{rel}: modified")
    media = manifest.get("media", {})
    problems.extend(_media_problems(out_dir, media))
    known = set(tracked) | {MANIFEST_NAME} | \
        ({media["rel"]} if media.get("rel") else set())
    problems.extend(f"{rel}: unexpected" for rel in _project_files(out_dir)
                    if rel not in known)
    return problems


def stale_generated_files(out_dir: str, fresh: set[str]) -> list[str]:
    """Previously generated files a regeneration no longer writes."""
    manifest_path = os.path.join(out_dir, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return []
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    return sorted(rel for rel in manifest.get("files", {}) if rel not in fresh)
