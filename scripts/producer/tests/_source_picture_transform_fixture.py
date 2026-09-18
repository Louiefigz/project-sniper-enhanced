"""Explicit TEST-only record/compiler metadata, never source/worker authority."""
from __future__ import annotations

import hashlib
from pathlib import Path

from _grade_contract_fixture import binding, declaration, frame, stream, terminal
from color.grade_observation_geometry import SourceObservationMetadata
from color.grade_observation_profile import V2_PROFILE
from color.grade_observation_read import BoundGradeObservation
from color.grade_source_class import SourceFrameValidator
from color.source_picture_transform import PictureTransformContext
from color.source_picture_transform_contract import TRANSFORM_POLICY
from cut_preview_io import digest


def transform_fixture(rate: str = "30000/1001", count: int = 3) -> tuple[PictureTransformContext, dict]:
    """Exercise real pure validators, with deliberately non-executable fake refs."""
    context = declaration(count)
    context.update(schemaVersion=2, sourceProfile="xvycc709")
    history = {"projectSha256": "9" * 64, "history": []}
    source = {**binding(context, rate), "projectHistorySha256": digest(history)}
    observed = stream(source, origin=24000)
    observed.update(width=8, height=4, transfer="iec61966-2-4",
        sourceMetadata=SourceObservationMetadata("h264", "left", "left", "1:1", "1:1").record())
    validator = SourceFrameValidator(source, context, observed, V2_PROFILE)
    for index in range(count):
        row = frame(index, observed)
        row.update(transfer="iec61966-2-4", chromaLocation="left", sampleAspectRatio="1:1")
        validator.add_frame(row)
    held = BoundGradeObservation(validator.finish(terminal(source)), "d" * 64, "e" * 64,
                                 raw_probe_sha256="f" * 64)
    authority = {"source": {"path": "/TEST-only/no-real-source.mp4", "sha256": source["sourceSha256"], "bytes": 123},
        "binding": source, "declaration": context,
        "expectedParents": {"projectSha256": "9" * 64, "planSha256": "7" * 64, "manifestSha256": "8" * 64},
        "projectHistory": history}
    tools = {name: {"path": f"/TEST-only/{name}", "sha256": str(index) * 64, "bytes": 123}
             for index, name in enumerate(("ffmpeg", "libavfilter", "libzimg"), 1)}
    tools.update(ffmpegVersion="8.0", zimgVersion="3.0.6")
    intent = {"schemaVersion": 1, "kind": TRANSFORM_POLICY, "scope": "picture-only",
        "geometry": "native-geometry-and-clock", "gamutPolicy": "reject-out-of-gamut",
        "chromaResampling": "bilinear-same-siting", "quantization": "8bit-no-dither"}
    return PictureTransformContext(held, authority, tools), intent


def no_authority_guard() -> None:
    """TEST-only no-op, deliberately not source/deadline/execution qualification."""


def held_test_file(path: Path) -> dict:
    """Hash exact local TEST input/tool bytes, never invent a real worker receipt."""
    resolved = path.resolve(strict=True)
    before = resolved.stat()
    value = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    after = resolved.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError("TEST input/tool changed while hashing")
    return {"path": str(resolved), "sha256": value.hexdigest(), "bytes": before.st_size}
