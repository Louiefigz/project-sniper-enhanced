"""Byte-bound base reuse; plan fingerprints alone never identify rendered media."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from render import RenderCtx

from fingerprints import base_plan_digest, file_sha256
from render_stage_roots import manifest_stage_payloads


def _stable_hash(path: str) -> str:
    """Hash a regular file and refuse a replacement or write during the read."""
    before = os.stat(path)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"base input is not a regular file: {path}")
    digest = file_sha256(path)
    after = os.stat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise RuntimeError(f"base input changed while hashing: {path}")
    return digest


def observe_inputs(manifest: dict) -> dict:
    """Bind base source metadata, media and transcripts; music stays post-base."""
    directory = Path(manifest["_path"]).absolute().parent if manifest.get("_path") else Path.cwd()
    paths: set[str] = set()
    rows = [*(manifest.get("sources") or []), *(manifest.get("broll") or [])]
    for row in rows:
        for key in ("path", "transcriptPath"):
            value = row.get(key)
            if value:
                paths.add(str((directory / value).absolute()))
    metadata = json.loads(json.dumps(manifest_stage_payloads(manifest)["manifest.base"]))
    return {"manifest": metadata,
            "files": {path: _stable_hash(path) for path in sorted(paths)}}


def plan_digests(plan: dict, policy: str) -> dict:
    """Full plan digests retain the existing audio-only and v2 finishing split."""
    from audio.program_finish_contract import finishing_free_plan
    source = finishing_free_plan(plan) if policy == "source-float-v2" else plan
    video = {key: value for key, value in source.items()
             if key not in ("audioGain", "audioEnhance")}
    return {"planDigest": base_plan_digest(source),
            "videoDigest": base_plan_digest(video)}


def seal_binding(base: str, plan: dict, inputs: dict, policy: str) -> dict:
    """Describe completed bytes; the caller must recheck its pre-render inputs."""
    return {"schemaVersion": 1, "baseSha256": _stable_hash(base),
            "inputs": inputs, **plan_digests(plan, policy)}


def inputs_from_path(path: str | None) -> dict:
    """Read the current manifest and observe its actual dependencies."""
    if not path:
        raise RuntimeError("base reuse requires a source manifest")
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["_path"] = os.path.abspath(path)
    return observe_inputs(manifest)


def binding_current(base: str, record: dict, manifest: str | None = None) -> bool:
    """Old receipts or changed base/source bytes cannot authorize any fast path."""
    binding = record.get("baseReuse")
    if not isinstance(binding, dict) or type(binding.get("schemaVersion")) is not int \
            or binding["schemaVersion"] != 1:
        return False
    try:
        return (binding.get("baseSha256") == _stable_hash(base)
                and binding.get("inputs") == inputs_from_path(manifest or record.get("manifestPath")))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def refresh_audio_binding(record: dict, plan: dict, base: str) -> dict | None:
    """Update only completed audio bytes/plan, preserving original source evidence."""
    previous = record.get("baseReuse")
    if not isinstance(previous, dict) or previous.get("schemaVersion") != 1:
        return None
    return seal_binding(base, plan, previous["inputs"], "legacy-v1")


def prepare_base_inputs(ctx: RenderCtx) -> None:
    """Hold original inputs before rendering; old intermediates need exact proof."""
    if not ctx.skip_graphics:
        return
    ctx.base_reuse_inputs = observe_inputs(ctx.manifest)
    if not ctx.resume:
        return
    try:
        with open(os.path.join(ctx.out_dir, "base.fingerprint.json")) as handle:
            record = json.load(handle)
        binding = record.get("baseReuse") or {}
        current = (binding_current(os.path.join(ctx.out_dir, "final.mp4"), record)
                   and binding.get("planDigest") == plan_digests(ctx.plan, ctx.audio_clock_policy)["planDigest"]
                   and record.get("audioClockPolicy") == ctx.audio_clock_policy)
    except (OSError, ValueError, TypeError, AttributeError):
        current = False
    if not current:
        ctx.resume = False


def completed_base_binding(ctx: RenderCtx) -> dict:
    """Never bless cached output using source hashes observed only after rendering."""
    if ctx.base_reuse_inputs is None or ctx.base_reuse_inputs != observe_inputs(ctx.manifest):
        raise RuntimeError("base render source inputs changed or were not held before rendering")
    return seal_binding(os.path.join(ctx.out_dir, "final.mp4"), ctx.plan,
                        ctx.base_reuse_inputs, ctx.audio_clock_policy)
