"""Live owned caption-tail completion and new-only ordinary Audit B staging.

Only trusted in-process assembly code receives this object. No parser creates
it and no serialized success flag can populate its private completion. The
actual body compositor must complete first; every failure is retained, without
fallback to caption-free caches or an independent caption re-encode.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from cut_preview_io import digest, real_directory
from guided_caption_dependencies import CaptionFile, Guard, _copy, hold_caption_file, read_caption_json, verify_caption_files
from guided_caption_layers import caption_page_clips
from guided_caption_projection import HeldCaptionProjection, read_caption_projection, stage_caption_dependencies


def _directory_identity(fd: int, path: Path) -> None:
    """The held destination FD must remain exactly the visible private directory."""
    real_directory(path)
    actual, visible = os.fstat(fd), path.lstat()
    if (actual.st_dev, actual.st_ino) != (visible.st_dev, visible.st_ino):
        raise RuntimeError("caption private candidate directory changed")


def stage_owned_caption_support(held: HeldCaptionProjection, destination: Path,
                               guard: Guard) -> tuple[CaptionFile, ...]:
    """Copy existing Audit B support without replacement into a new owned stage."""
    real_directory(destination)
    root = Path(held.root)
    if destination == root or destination.is_relative_to(root):
        raise RuntimeError("caption staging cannot mutate the original opening tree")
    staged = stage_caption_dependencies(held, held.binding, destination / "held-caption-support", guard)
    fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _directory_identity(fd, destination)
        for row in staged:
            guard()
            _copy(row, fd, guard)  # Existing bounded no-follow/O_EXCL implementation, no overwrite.
        os.fsync(fd)
        _directory_identity(fd, destination)
    finally:
        os.close(fd)
    result = tuple(CaptionFile(str(destination / Path(row.path).name), row.sha256, row.size_bytes) for row in staged)
    verify_caption_files(staged, guard)
    verify_caption_files(result, guard)
    guard()
    return result


def read_owned_caption_support(held: HeldCaptionProjection, destination: Path,
                              guard: Guard) -> list[dict]:
    """Require the entire original Audit B closure beside the final candidate."""
    names = {row["name"] for row in held.data["authority"]["files"].values()} | {"caption_authority.json"}
    originals = {Path(row.path).name: row for row in held.files}
    rows = tuple(CaptionFile(str(destination / name), originals[name].sha256, originals[name].size_bytes)
                 for name in sorted(names))
    verify_caption_files(rows, guard)
    return [{"path": row.path, "sha256": row.sha256, "sizeBytes": row.size_bytes} for row in rows]


@dataclass
class OwnedCaptionExecution:
    """One live renderer owner's exact original pages and single-use completion."""

    held: HeldCaptionProjection
    guard: Guard
    _completion: dict | None = field(default=None, init=False, repr=False)
    _staged: tuple[CaptionFile, ...] | None = field(default=None, init=False, repr=False)

    def clips(self) -> tuple[dict, ...]:
        """Always derive page records from the strongly held original projection."""
        self.guard()
        return caption_page_clips(self.held)

    def assert_plan(self, plan: dict, plan_path: str) -> None:
        """The uncaptioned or different-plan assembler cannot acquire this live tail."""
        if plan_path != self.held.binding.plan.path or (plan.get("captions") or {}).get("burn") is not True \
                or type(plan.get("captionsTrack")) is not dict \
                or digest(plan) != digest(read_caption_json(self.held.binding.plan, self.guard)):
            raise RuntimeError("owned caption execution differs from the exact original captioned plan")
        self.guard()

    def stage(self, output: str) -> None:
        """One exact private stage, never the old caption-free checkpoint namespace."""
        if self._staged is not None:
            raise RuntimeError("owned caption support staging was repeated")
        self._staged = stage_owned_caption_support(self.held, Path(output).parent, self.guard)

    def complete(self, output: str, proof: dict) -> None:
        """Called only AFTER actual bound composition+retention by its live owner."""
        self.guard()
        if self._completion is not None or self._staged is None:
            raise RuntimeError("owned caption completion was repeated or lacks staged support")
        observed = hold_caption_file(Path(output), self.guard)
        encoded, oracle = proof["output"], proof["prefixOracle"]
        if proof["outputPath"] != output or encoded != {"path": output, "sha256": observed.sha256,
                "size_bytes": observed.size_bytes} or proof["deliveryApproved"] is not False \
                or oracle.get("layerPolicy", {}).get("fullCaptionTail") != len(self.clips()):
            raise RuntimeError("owned caption completion differs from actual combined output")
        read_caption_projection(self.held, self.held.binding, self.guard)
        verify_caption_files(self._staged, self.guard)
        self._completion = {"output": observed, "projectionHash": self.held.data_hash,
                            "pageGraphHash": digest(list(self.clips()))}
        self.guard()

    def finish(self, output: str) -> dict:
        """No serialized flag can skip the old path without this live completion."""
        self.guard()
        value = self._completion
        if value is None or value["output"].path != output or self._staged is None \
                or value["projectionHash"] != self.held.data_hash \
                or value["pageGraphHash"] != digest(list(self.clips())):
            raise RuntimeError("owned caption burn lacks its exact live combined-picture completion")
        verify_caption_files((value["output"], *self._staged), self.guard)
        read_caption_projection(self.held, self.held.binding, self.guard)
        return {"cues": len(self.held.data["compilation"]["cues"]), "burned": True,
            "alphaShards": len(self.held.data["shards"]["entries"]), "renderedShards": 0,
            "cacheHits": 0, "authorityHash": self.held.data["authority"]["authorityHash"],
            "sharedHeldPages": len(self.clips()), "duplicateCaptionEncodeSkipped": True,
            "completionScope": "live-owned-combined-picture-not-human-approval"}
