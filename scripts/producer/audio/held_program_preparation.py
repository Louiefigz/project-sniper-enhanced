"""Read an actually held opening base/master for isolated ordinary assembly.

The separately held event SHA comes from the authenticated caller, not directory
discovery. This module proves media dependencies, never opening/body approval.
"""
from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio.assemble_publication import require_settled
from audio.program_master_selection import (
    HeldMasterSelection, read_master_selection, selection_implementation,
)
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from cut_delivery_authority import DELIVERY_NAME
from cut_manifestation_authority import MANIFESTATION_NAME, verify_manifestation
from cut_preview_io import bound_json, file_hash, real_directory
from graphics.frame_quantization import require_graphic_frame_clock

_REQUIRED = ("timeline_map.json", MANIFESTATION_NAME, DELIVERY_NAME,
             "base.fingerprint.json", "base_plan.json")
_OPTIONAL = ("cover.png", "geometry_predictions.json",
             ".sniper-learning/geometry_residuals.jsonl")


@dataclass(frozen=True)
class HeldProgramPreparation:
    """Actual original artifact ownership, plus unchanged bounded base support."""

    selection: HeldMasterSelection
    support: dict[str, str]

    @property
    def root(self) -> Path:
        """Keep source/bus/master dependencies in their original artifact root."""
        return self.selection.context.artifact_root


def _reference(value: object) -> tuple[Path, str]:
    """Reject incomplete, guessed or malformed import references before media."""
    if type(value) is not tuple or len(value) != 2:
        raise RuntimeError("held program preparation requires an exact event path/SHA pair")
    path, sha = value
    if type(path) is not str or type(sha) is not str or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise RuntimeError("held program preparation reference is malformed")
    result = Path(path)
    if not result.is_absolute() or result.resolve(strict=True) != result:
        raise RuntimeError("held program preparation path must be canonical")
    return result, sha


def _private_destination(job: Any, selection: HeldMasterSelection) -> None:
    """An imported first body attempt cannot overwrite opening or prior output."""
    output = Path(job.out)
    real_directory(output.parent)
    root = selection.context.artifact_root
    if output.name != "final.mp4" or output.parent == root or output.parent.is_relative_to(root):
        raise RuntimeError("held program output must be a separate private body directory")
    if stat.S_IMODE(output.parent.stat().st_mode) != 0o700 or any(output.parent.iterdir()):
        raise RuntimeError("held program output directory must be new, empty and private (0700)")


def _inputs(job: Any, selection: HeldMasterSelection) -> None:
    """Require the unchanged full candidate, not merely audio-equivalent edits."""
    context, event = selection.context, selection.event
    if job.audio_clock_policy != SOURCE_FLOAT_POLICY_V2 or job.audio_only:
        raise RuntimeError("held program preparation requires unchanged source-float-v2 assembly")
    if Path(job.base) != context.base_path or Path(job.manifest or "") != context.manifest_path:
        raise RuntimeError("held program preparation base or manifest differs from selection")
    if not job.plan_path or file_hash(Path(job.plan_path)) != event["planSha256"] \
            or job.plan != selection.plan:
        raise RuntimeError("held program preparation requires exact unchanged plan bytes")
    fingerprint = context.artifact_root / "base.fingerprint.json"
    if Path(job.fingerprint_path or "") != fingerprint:
        raise RuntimeError("held program preparation requires its original base fingerprint")
    expected = selection.master.source_bus.receipt["receiptHash"]
    if job.source_bus_receipt_hash is not None and job.source_bus_receipt_hash != expected:
        raise RuntimeError("held program preparation source receipt differs")
    clock = getattr(job, "graphic_frame_clock", None)
    if clock is not None:
        bus = selection.master.source_bus
        require_graphic_frame_clock(clock, (bus.frame_rate, bus.frames))


def _support(selection: HeldMasterSelection) -> dict[str, str]:
    """Hold exact known sidecars without moving or re-sealing original proof."""
    root = selection.context.artifact_root
    require_settled(root)
    paths = [root / name for name in _REQUIRED]
    paths += [root / name for name in _OPTIONAL if (root / name).exists() or (root / name).is_symlink()]
    result = {str(path): file_hash(path) for path in paths}
    if bound_json(root / "base_plan.json") != selection.plan:
        raise RuntimeError("held program preparation base plan differs")
    fingerprint = bound_json(root / "base.fingerprint.json")
    if fingerprint.get("sourceAudioBusReceiptHash") != selection.master.source_bus.receipt["receiptHash"]:
        raise RuntimeError("held program preparation fingerprint lacks exact source receipt")
    verify_manifestation(str(root), selection.plan)
    return result


def load_held_program_preparation(job: Any) -> HeldProgramPreparation | None:
    """Reopen supplied actual selection; an invalid import never falls back."""
    reference = getattr(job, "held_program_selection", None)
    if reference is None:
        return None
    selection = read_master_selection(*_reference(reference))
    _inputs(job, selection)
    _private_destination(job, selection)
    preparation = HeldProgramPreparation(selection, _support(selection))
    assert_held_program_preparation(preparation)
    return preparation


def assert_held_program_preparation(preparation: HeldProgramPreparation) -> None:
    """Reobserve original selection and support before any private publication."""
    selection = preparation.selection
    require_settled(preparation.root)
    if selection_implementation() != selection.event["selectionImplementation"]:
        raise RuntimeError("held program preparation implementation changed")
    paths = {str(selection.context.event_path): selection.event_sha256,
        str(selection.context.base_path): selection.event["baseSha256"],
        str(selection.context.plan_path): selection.event["planSha256"],
        str(selection.context.manifest_path): selection.event["manifestSha256"]}
    for path, expected in {**paths, **preparation.support}.items():
        if file_hash(Path(path)) != expected:
            raise RuntimeError("held program preparation support changed")


def preparation_reuse_evidence(preparation: HeldProgramPreparation) -> dict:
    """Describe actual reuse without minting a review or delivery receipt."""
    selection = preparation.selection
    return {"scope": "held-full-program-preparation-not-approval",
        "selectionEventSha256": selection.event_sha256,
        "baseSha256": selection.event["baseSha256"],
        "sourceBusReceiptHash": selection.master.source_bus.receipt["receiptHash"],
        "programMasterReceiptHash": selection.master.receipt["receiptHash"],
        "masterPcmSha256": selection.master.receipt["masteredAudio"]["sha256"],
        "baseRendered": False, "programRemastered": False, "baseAudioSelected": False}
