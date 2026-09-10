"""Complete actual body A/V, selected master and whole Audit B read observations.

No directory-discovered result can call this authority. Callers separately hold
the actual worker receipt bytes and original approved inputs. Readback does not
render, edit plans, replace media, rerun authors or create delivery approval.
"""
from __future__ import annotations

from dataclasses import asdict
from fractions import Fraction
from pathlib import Path

from audio.assemble_publication import require_settled
from audio.audio_mix_delivery import measure_delivery
from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from audio.program_audio_clock import exact_aac_audio_clock
from audio.program_master_selection import HeldMasterSelection
from cut_delivery_authority import verify_delivered_cuts
from cut_preview_io import bound_json, digest, file_hash
from guided_opening_inputs import OpeningInputs, closed, hash_value
from guided_opening_picture import observe_picture
from guided_opening_result import held_ref
from guided_body_qc import (artifact_reference, observe_body_qc, observe_body_support,
                            verify_body_support)
from guided_caption_profile import caption_profile
from guided_caption_execution import read_owned_caption_support
from guided_caption_projection import HeldCaptionProjection
from palmier.process_deadline import process_timeout


def _reference(path: Path) -> dict:
    """Bind a regular same-byte result, never claim authority from the hash itself."""
    return artifact_reference(path)


def _delivery(root: Path, values: tuple, final: dict) -> dict:
    """Bind the actual retained full-master→AAC receipt to unchanged final picture."""
    reference, composition, selection = values
    path = Path(reference["path"])
    if not path.is_relative_to(root / "body-candidate") or path.name != "delivery-receipt.json":
        raise RuntimeError("body delivery receipt escaped its actual private assembly")
    held = _reference(path)
    row = bound_json(path, held["sha256"])
    expected_hash = hash_value(reference["receiptHash"])
    if row["receiptHash"] != expected_hash or digest({key: item for key, item in row.items() if key != "receiptHash"}) != expected_hash:
        raise RuntimeError("body actual AAC delivery receipt changed")
    expected = {"schemaVersion": 2, "kind": "ordinary-program-delivery", "approved": False,
        "audioClockPolicy": "source-float-v2", "programMasterReceiptHash": selection.master.receipt["receiptHash"],
        "audioProgramInputHash": selection.master.receipt["audioProgramInputHash"],
        "path": composition["outputPath"], "sha256": final["sha256"], "picture": final["pictureCopy"],
        "audioClock": final["audioClock"], "delivery": final["audioDelivery"],
        "audiblePathAacEncodes": 1, "legacyPictureTransportAacStillExecuted": True, "receiptHash": expected_hash}
    closed(row, set(expected), "body actual full-program AAC delivery")
    if digest(row) != digest(expected):
        raise RuntimeError("body AAC is not from the exact held whole master/picture/clock")
    return {**held, "receiptHash": expected_hash, "programMasterReceiptHash": selection.master.receipt["receiptHash"],
        "sourcePcmSha256": file_hash(Path(selection.master.path)), "samples": selection.master.source_bus.samples,
        "audiblePathAacEncodes": 1, "approved": False}


def observe_body_media(root: Path, inputs: OpeningInputs, selection: HeldMasterSelection, evidence: dict) -> dict:
    """Reobserve both complete pictures, exact AAC clock and full decoded loudness."""
    require_settled(root / "body-candidate")
    composition = evidence["composition"]
    support = observe_body_support(root, inputs.documents["candidatePlan"], composition)
    caption_support = _caption_support(root, inputs, evidence)
    picture_path = held_ref(composition["retainedPicture"], root, root / "picture-only.mp4")
    if composition["output"]["sha256"] != composition["retainedPicture"]["sha256"] \
            or composition["output"]["size_bytes"] != composition["retainedPicture"]["sizeBytes"]:
        raise RuntimeError("body retained picture differs from actual prefix encoded bytes")
    authority, tools = inputs.documents["authority"], selection.master.source_bus.admission.tools
    expected = authority["frameRate"], authority["totalFrames"], (authority["target"]["width"], authority["target"]["height"])
    picture = observe_picture(picture_path, expected, tools)
    final = observe_picture(root / "body-candidate/final.mp4", expected, tools)
    source = observe_picture_source(str(picture_path), float(Fraction(expected[1], 1) / Fraction(expected[0])), picture["sha256"])
    final["pictureCopy"] = verify_picture_copy(source, final["path"])
    final["audioClock"] = exact_aac_audio_clock(final["path"], tools["ffprobe"]["path"], selection.master.source_bus.samples)
    final["audioDelivery"] = measure_delivery(final["path"])
    if final["audioDelivery"]["qualified"] is not True:
        raise RuntimeError("body complete encoded audio failed the existing full-program delivery policy")
    delivery = _delivery(root, (evidence["programDeliveryReceipt"], composition, selection), final)
    cut = verify_delivered_cuts(str(root / "body-candidate"), final["path"], inputs.documents["candidatePlan"])
    audit = observe_body_qc(root, final, inputs.documents["candidatePlan"])
    for row in (picture, final):
        held_ref(row, root)
    verify_body_support(root, support)
    return {"picture": picture, "final": final, "programDelivery": delivery,
        "audit": audit, "cutDelivery": asdict(cut), "support": support, **caption_support}


def _caption_support(root: Path, inputs: OpeningInputs, evidence: dict) -> dict:
    """Only original held pages may bind an explicit captioned final candidate."""
    held = evidence.get("captions")
    if not caption_profile(inputs.value.get("profile")):
        if held is not None:
            raise RuntimeError("uncaptioned body acquired a caption projection")
        return {}
    if type(held) is not HeldCaptionProjection:
        raise RuntimeError("captioned body read lacks the exact original held projection")
    return {"captionSupport": read_owned_caption_support(held, root / "body-candidate", process_timeout)}


def verify_body_media_files(root: Path, value: dict) -> None:
    """Final deduplicated artifact bytes after observation; no directory scanning."""
    rows = [value["picture"], value["final"], value["programDelivery"], value["audit"], *value["audit"]["frames"]]
    seen = set()
    for row in rows:
        key = row["path"], row["sha256"]
        if key not in seen:
            held_ref(row, root)
            seen.add(key)
    verify_body_support(root, value["support"])
    for row in value.get("captionSupport", []):
        held_ref(row, root / "body-candidate", root / "body-candidate" / Path(row["path"]).name)
