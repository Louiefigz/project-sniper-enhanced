"""Shared real-media fixture for the private prebound compositor tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path

from _common import pl  # noqa: F401
from headless.media_probe import artifact_sha256, probe_media_artifact
from headless.prebound_compositor import (
    PreboundCompositorContextV1,
    compositor_build_digest,
)
from headless.prebound_compositor_media import media_ref
from headless.quality_pass_contract import (
    ArtifactRefV1,
    GraphicAssetRefV1,
    graphic_render_intent_digest,
    parse_quality_pass_input,
)
from headless.quality_pass_types import CandidatePlanV1, CompositeRequestV1
from headless.repair_intent import apply_repair, current_accent_policy
from test_quality_pass_contract import _approved, _document, _plan


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-1000:])


def sample_rgb(ffmpeg: str, path: Path, seconds: float) -> tuple[float, ...]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(seconds),
        "-i",
        str(path),
        "-vf",
        "crop=88:20:10:80,format=rgb24",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode or len(completed.stdout) != 88 * 20 * 3:
        raise RuntimeError(completed.stderr.decode()[-1000:])
    values = completed.stdout
    return tuple(sum(values[index::3]) / (len(values) // 3) for index in range(3))


def _write(path: Path, raw: bytes) -> ArtifactRefV1:
    path.write_bytes(raw)
    path.chmod(0o600)
    return ArtifactRefV1(path.name, artifact_sha256(str(path)), path.stat().st_size)


def _overlay(ffmpeg: str, path: Path, color: str) -> None:
    source = (
        "color=black@0.0:s=108x192:r=30:d=1,format=yuva444p10le,"
        f"drawbox=x=10:y=80:w=88:h=20:color={color}@1:t=fill:replace=1"
    )
    _run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            str(path),
        ]
    )
    path.chmod(0o600)


def transparent_overlay(ffmpeg: str, path: Path) -> None:
    source = "color=black@0.0:s=108x192:r=30:d=1,format=yuva444p10le"
    _run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            str(path),
        ]
    )
    path.chmod(0o600)


def _base(ffmpeg: str, path: Path) -> None:
    _run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=108x192:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=48000:d=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(path),
        ]
    )
    path.chmod(0o600)


class Fixture:
    """Builds immutable parent and changed-graphic artifacts for one test."""

    def __init__(self, root: Path, ffmpeg: str, ffprobe: str):
        self.root, self.ffmpeg, self.ffprobe = root, ffmpeg, ffprobe
        self.sources = root / "sources"
        self.sources.mkdir(mode=0o700)
        self.plan = _plan()
        self.plan["graphicsTrack"][0].update(
            {"outStart": 0.5, "outEnd": 1.5, "placement": {"x": 0, "y": 0}}
        )
        self.plan["music"] = {"enabled": False}
        self.request = parse_quality_pass_input(_document(self.plan))
        self.parent, self.changed, self.mapping = self._artifacts()

    def _media(self, path: Path, relative: str):
        probe = probe_media_artifact(str(path), self.ffprobe, 30)
        return media_ref(relative, probe)

    def json_ref(self, name: str, document: object) -> tuple[ArtifactRefV1, Path]:
        raw = json.dumps(
            document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
        path = self.sources / name
        return _write(path, raw), path

    def graphic(self, path: Path, receipt: ArtifactRefV1, plan: dict):
        row = plan["graphicsTrack"][0]
        digest = graphic_render_intent_digest(row)
        seed = path.stem
        asset = GraphicAssetRefV1(
            row["id"],
            digest,
            self._media(path, path.name),
            receipt,
            hashlib.sha256(f"artifact-{seed}".encode()).hexdigest(),
            hashlib.sha256(f"build-{seed}".encode()).hexdigest(),
        )
        receipt_path = self.sources / receipt.relative_path
        return asset, {asset.media.artifact: path, asset.receipt: receipt_path}

    def _parent(self, base_path: Path, old: GraphicAssetRefV1):
        parent = _approved(self.plan)
        base = self._media(base_path, "base.mp4")
        clip = [
            {
                "anchor": "free-band",
                "graphicId": old.graphic_id,
                "mediaSha256": old.media.artifact.sha256,
                "outEnd": 1.5,
                "outStart": 0.5,
                "renderReceiptSha256": old.receipt.sha256,
                "x": 0,
                "y": 0,
            }
        ]
        clips_ref, clips_path = self.json_ref("parent-clips.json", clip)
        base_receipt, base_receipt_path = self.json_ref(
            "base-receipt.json", {"base": base.artifact.sha256}
        )
        base_plan, base_plan_path = self.json_ref("base-plan.json", self.plan)
        timeline, timeline_path = self.json_ref("timeline.json", {"cuts": []})
        final = dataclasses.replace(
            base,
            artifact=dataclasses.replace(
                base.artifact, relative_path="parent-final.mp4"
            ),
        )
        parent = dataclasses.replace(
            parent,
            base=base,
            base_receipt=base_receipt,
            base_plan=base_plan,
            timeline_map=timeline,
            prebound_clips=clips_ref,
            graphics_assets=(old,),
            final=final,
        )
        mapping = {
            base.artifact: base_path,
            base_receipt: base_receipt_path,
            base_plan: base_plan_path,
            timeline: timeline_path,
            clips_ref: clips_path,
        }
        return parent, mapping

    def _artifacts(self):
        base_path = self.sources / "base.mp4"
        old_path = self.sources / "old.mov"
        changed_path = self.sources / "new.mov"
        _base(self.ffmpeg, base_path)
        _overlay(self.ffmpeg, old_path, "0x054BC9")
        _overlay(self.ffmpeg, changed_path, "yellow")
        old_receipt, _old_path = self.json_ref("old-receipt.json", {"render": "old"})
        new_receipt, _new_path = self.json_ref("new-receipt.json", {"render": "new"})
        old, _old_mapping = self.graphic(old_path, old_receipt, self.plan)
        application = apply_repair(
            self.request.repair,
            self.request.repair.expected_parent,
            self.plan,
            current_accent_policy(),
        )
        changed, changed_map = self.graphic(
            changed_path, new_receipt, application.decoded_plan()
        )
        parent, parent_map = self._parent(base_path, old)
        return parent, changed, {**parent_map, **changed_map}

    def composite_request(self) -> CompositeRequestV1:
        application = apply_repair(
            self.request.repair, self.parent.ref, self.plan, current_accent_policy()
        )
        candidate = CandidatePlanV1(self.parent, application)
        return CompositeRequestV1(
            self.request.request_digest, candidate, (self.changed,)
        )

    def context(self, candidate: Path) -> PreboundCompositorContextV1:
        return PreboundCompositorContextV1(
            str(candidate),
            lambda ref: str(self.mapping[ref]),
            self.ffmpeg,
            self.ffprobe,
            compositor_build_digest(),
            60,
        )
