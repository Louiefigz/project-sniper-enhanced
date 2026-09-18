"""Held exact-rate graphic intent and actual sealed-runtime proof comparison.

This is the private ordinary-at-rate adapter, not the fixed30 presealed V2
launch. Expected copy, frame count, rate, archive and assets are derived before
the call from the actual reviewed original entry, never from its result.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import digest, file_hash
from graphics import graphics_render
from graphics.frame_quantization import hyperframes_duration
from graphics.render_rate import RenderRate
from guided_graphic_template import read_graphic_template
from guided_opening_picture import observe_picture
from headless.container_io import CompositionInput, SealedInput, create_snapshot
from headless.runtime_receipt import validate_runtime_attestation


@dataclass(frozen=True)
class OpeningGraphicIntent:
    """Before-spawn immutable original animation/render facts."""

    row: dict
    rate: RenderRate
    snapshot: SealedInput
    dimensions: tuple[int, int]
    copy: tuple[str, ...]
    key: str


def graphic_intent(row: dict, root: Path, frame_rate: str) -> OpeningGraphicIntent:
    """Reuse ordinary source sealing/quantization with exact controller endpoints."""
    entry, template = row["entry"], read_graphic_template(row, frame_rate)
    rate, frames, html = template.rate, template.frames, template.html
    relative = f"compositions/{entry['kind']}.html"
    source = CompositionInput(relative, html, render_intent={"fps": rate.token},
                               duration=hyperframes_duration(frames, rate.numeric))
    sealed = root / "expected-seal"
    sealed.mkdir(mode=0o700)
    snapshot = create_snapshot(graphics_render.PIPELINE_ROOT, source, entry.get("spec") or {}, str(sealed))
    key = graphics_render._sealed_hash(entry["kind"], snapshot, rate.token)
    return OpeningGraphicIntent(row, rate, snapshot, template.dimensions, template.copy, key)


def intent_record(intent: OpeningGraphicIntent) -> dict:
    """Persist the exact independent expected request before any container spawn."""
    return {"entry": intent.row["entry"], "entryHash": intent.row["entryHash"],
        "frameRate": intent.rate.token, "startFrame": intent.row["startFrame"],
        "endFrameExclusive": intent.row["endFrameExclusive"],
        "fullAnimationFrames": intent.row["endFrameExclusive"] - intent.row["startFrame"],
        "dimensions": list(intent.dimensions), "expectedCopy": list(intent.copy), "expectedKey": intent.key,
        "snapshot": {"path": intent.snapshot.path, "sha256": intent.snapshot.sha256,
            "manifest": list(intent.snapshot.manifest), "assetBindings": list(intent.snapshot.asset_bindings)}}


def verify_graphic_result(result: dict, intent: OpeningGraphicIntent, context: tuple[str, str, dict]) -> dict:
    """Require same expected archive/name/rate/copy and actual full decoded frame clock."""
    image_id, name, tools = context
    path, proof = Path(result["path"]), result["proof"]
    frames = intent.row["endFrameExclusive"] - intent.row["startFrame"]
    asset, runtime = proof.get("asset", {}), proof.get("runtimeAttestation", {})
    if result.get("cached") is not False or result.get("key") != intent.key or result.get("fmt") != "mp4" \
            or result.get("fps") != intent.rate.token or result.get("kind") != intent.row["entry"]["kind"] \
            or asset.get("frameCount") != frames or asset.get("fps") != intent.rate.numeric:
        raise RuntimeError("opening rendered graphic differs from its held original rate/entry/frame count")
    if runtime.get("snapshotSha256") != intent.snapshot.sha256 \
            or digest(runtime.get("snapshotManifest")) != digest(list(intent.snapshot.manifest)) \
            or digest(proof.get("assetInputs")) != digest(list(intent.snapshot.asset_bindings)) \
            or proof.get("copy", {}).get("expected") != list(intent.copy) \
            or runtime.get("containerBeforeOutput", {}).get("Name") != "/" + name \
            or runtime.get("containerAfterOutput", {}).get("Name") != "/" + name:
        raise RuntimeError("opening graphic sealed source/assets/copy or owned container identity differs")
    before = file_hash(path)
    if before != asset.get("sha256"):
        raise RuntimeError("opening graphic bytes differ from actual returned proof")
    validate_runtime_attestation(runtime, str(path), before, image_id)
    clock = observe_picture(path, (intent.rate.token, frames, intent.dimensions), tools)
    return {"actualAsset": clock, "renderKey": intent.key, "actualProof": proof,
        "inputArchive": {"path": str(path) + ".input.tar", "sha256": file_hash(Path(str(path) + ".input.tar"))},
        "proofSidecar": {"path": str(path) + ".proof.json", "sha256": file_hash(Path(str(path) + ".proof.json"))},
        "runtimeSidecar": {"path": str(path) + ".runtime.json", "sha256": file_hash(Path(str(path) + ".runtime.json"))}}


def verify_graphics_unchanged(rows: list[dict]) -> None:
    """No already-proved source asset may change while the range is composited."""
    for row in rows:
        refs = [row[key] for key in ("actualAsset", "inputArchive", "proofSidecar", "runtimeSidecar")]
        refs.append({"path": row["requestPath"], "sha256": row["requestSha256"]})
        if "captionLayoutObservation" in row:
            refs.append(row["captionLayoutObservation"]["observation"])
        if any(file_hash(Path(ref["path"])) != ref["sha256"] for ref in refs):
            raise RuntimeError("opening actual graphic/archive/proof/request bytes changed after render")
