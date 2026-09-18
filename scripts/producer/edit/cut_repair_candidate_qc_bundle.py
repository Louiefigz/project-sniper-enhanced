"""Persist/reopen one passing automated-QC bundle by preparation hash."""
from __future__ import annotations

import os

from edit.cut_repair_candidate_qc_contract import load_candidate_authority
from edit.cut_repair_candidate_qc_store import (
    ensure_real_directory,
    publish_json,
)
from edit.cut_repair_candidate_qc_types import (
    CandidateQcContractError,
    QcRun,
)
from edit import cut_repair_visual_lip_sync_contract as visual_contract
from edit.cut_repair_context_sources import (
    digest,
    require_hash,
    require_keys,
    stable_json,
)

_LANES = ("alignment", "vad", "retranscription", "seam")
_ITEM_KEYS = {
    "status", "receiptHash", "candidateCompositeSha256", "receipt"}
_BUNDLE_KEYS = {
    "schemaVersion", "kind", "preparationHash", "candidateDescriptorHash",
    "toolManifestHash", "operationHash", "candidateCompositeSha256",
    "alignment", "vad", "retranscription", "seam",
    "operatorAuditionIncluded",
}
_POINTER_KEYS = {
    "schemaVersion", "kind", "preparationHash", "bundleHash",
    "candidateDescriptorHash", "candidateCompositeSha256",
}


def _receipt_item(run: QcRun, lane: str, value: dict) -> dict:
    if value.get("status") != "bounded-pass" \
            or not isinstance(value.get("receiptPath"), str):
        raise CandidateQcContractError(
            "automated QC bundle requires four passing lanes")
    receipt, observed = _read_json(
        value["receiptPath"], f"{lane} automated QC receipt")
    receipt_hash = require_hash(
        value.get("receiptHash"), f"{lane} automated QC receipt hash")
    expected = (
        receipt_hash, run.authority.descriptor["operationHash"],
        run.authority.candidate_sha256)
    actual = (
        observed, receipt.get("operationHash"),
        receipt.get("candidateCompositeSha256"))
    if actual != expected or digest(receipt) != receipt_hash:
        raise CandidateQcContractError(
            f"{lane} automated QC receipt is stale")
    return {
        "status": "bounded-pass",
        "receiptHash": receipt_hash,
        "candidateCompositeSha256": run.authority.candidate_sha256,
        "receipt": receipt,
    }


def _read_json(path: str, label: str) -> tuple[dict, str]:
    try:
        return stable_json(path, label)
    except (OSError, ValueError, TypeError) as exc:
        raise CandidateQcContractError(f"{label} is unreadable or stale") \
            from exc


def _bundle(run: QcRun, lanes: dict[str, dict]) -> dict:
    items = {lane: _receipt_item(run, lane, lanes[lane])
             for lane in _LANES}
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-automated-qc-bundle",
        "preparationHash": run.authority.preparation_hash,
        "candidateDescriptorHash":
            run.authority.package["reviewCandidateDescriptorHash"],
        "toolManifestHash": run.tools.manifest_hash,
        "operationHash": run.authority.descriptor["operationHash"],
        "candidateCompositeSha256": run.authority.candidate_sha256,
        **items,
        "operatorAuditionIncluded": False,
    }


def _object_directory(producer: str) -> str:
    return os.path.join(
        producer, ".sniper-authority-v1", "objects", "cut-repairs")


def _pointer_path(producer: str, preparation_hash: str) -> str:
    return os.path.join(
        producer, ".sniper-authority-v1", "sagas",
        "cut-repair-automated-qc", "records", f"{preparation_hash}.json")


def _prepare_pointer_path(producer: str, preparation_hash: str) -> str:
    sagas = os.path.join(
        producer, ".sniper-authority-v1", "sagas")
    root = os.path.join(sagas, "cut-repair-automated-qc")
    records = os.path.join(root, "records")
    ensure_real_directory(sagas)
    ensure_real_directory(root)
    ensure_real_directory(records)
    return _pointer_path(producer, preparation_hash)


def persist_automated_qc_bundle(
    run: QcRun,
    lanes: dict[str, dict],
) -> tuple[dict, str, str]:
    """Content-address one pass bundle and bind its preparation exactly once."""
    value = _bundle(run, lanes)
    bundle_hash = digest(value)
    bundle_path = os.path.join(
        _object_directory(run.authority.producer), f"{bundle_hash}.json")
    if publish_json(bundle_path, value) != bundle_hash:
        raise CandidateQcContractError("automated QC bundle hash changed")
    pointer = {
        "schemaVersion": 1,
        "kind": "cut-repair-automated-qc-pointer",
        "preparationHash": run.authority.preparation_hash,
        "bundleHash": bundle_hash,
        "candidateDescriptorHash":
            run.authority.package["reviewCandidateDescriptorHash"],
        "candidateCompositeSha256": run.authority.candidate_sha256,
    }
    publish_json(_prepare_pointer_path(
        run.authority.producer, run.authority.preparation_hash), pointer)
    return value, bundle_hash, bundle_path


def _selected_output_authority(
    authority,
    selected: dict,
) -> tuple[dict, dict, dict]:
    frames = selected.get("outputFrameRange")
    if not isinstance(frames, dict):
        raise CandidateQcContractError(
            "selected take output frame range is absent")
    first = frames.get("firstFrame")
    end = frames.get("endFrameExclusive")
    window = authority.window
    if any(type(value) is not int for value in (first, end)):
        raise CandidateQcContractError(
            "selected take output frame range is malformed")
    output_frames = {
        **frames,
        "fpsNumerator": window.fps_numerator,
        "fpsDenominator": window.fps_denominator,
    }
    output_samples = {
        "startSample": first * window.fps_denominator
        * window.sample_rate // window.fps_numerator,
        "endSampleExclusive": end * window.fps_denominator
        * window.sample_rate // window.fps_numerator,
        "sampleRate": window.sample_rate,
    }
    region = selected.get("visualSpeechRegion")
    if not isinstance(region, dict):
        raise CandidateQcContractError(
            "selected take visual speech region is absent")
    visual_region = {
        "x": region.get("xPpm"), "y": region.get("yPpm"),
        "width": region.get("widthPpm"), "height": region.get("heightPpm"),
    }
    return output_frames, output_samples, visual_region


def _validate_seam_authority(authority, receipt: dict) -> None:
    expected = ("passed" if authority.picture_dirty
                else "not-applicable-audio-only")
    if receipt.get("lipSyncDisposition") != expected:
        raise CandidateQcContractError(
            "seam lip-sync disposition contradicts repair picture authority")
    if not authority.picture_dirty:
        if visual_contract.VISUAL_SEAM_FIELDS.intersection(receipt):
            raise CandidateQcContractError(
                "audio-only seam cannot carry picture-selection evidence")
        return
    selection_hash = require_hash(
        authority.alternate_take_selection_hash,
        "authoritative alternate-take selection")
    if receipt.get("alternateTakeSelectionReceiptHash") != selection_hash:
        raise CandidateQcContractError(
            "seam visual proof binds another alternate-take selection")
    visual_contract.validate_visual_seam(
        receipt, authority.descriptor["operationHash"],
        authority.candidate_sha256)
    visual = receipt["visualOracleReceipt"]
    selected = authority.alternate_take_selection
    if not isinstance(selected, dict):
        raise CandidateQcContractError(
            "picture-dirty bundle has no alternate-take authority")
    output_frames, output_samples, visual_region = _selected_output_authority(
        authority, selected)
    pairs = (
        (visual.get("preparationHash"), authority.preparation_hash),
        (visual.get("candidateSetHash"), selected.get("candidateSetHash")),
        (visual.get("selectionHash"), selected.get("selectionHash")),
        (visual.get("selectedCandidateId"), selected.get("selectedCandidateId")),
        (visual.get("sourceId"), selected.get("sourceId")),
        (visual.get("sourceMediaSha256"), selected.get("sourceMediaSha256")),
        (visual.get("sourceFrameRange"), selected.get("sourceFrameRange")),
        (visual.get("sourceSampleRange"), selected.get("sourceSampleRange")),
        (visual.get("outputFrameRange"), output_frames),
        (visual.get("outputSampleRange"), output_samples),
        (visual.get("visualSpeechRegionPpm"), visual_region),
    )
    if any(observed != expected for observed, expected in pairs):
        raise CandidateQcContractError(
            "seam visual proof does not bind the selected take authority")


def _validate_bundle(value: dict, authority, bundle_hash: str) -> None:
    require_keys(value, _BUNDLE_KEYS, _BUNDLE_KEYS, "automated QC bundle")
    expected = (
        1, "cut-repair-automated-qc-bundle",
        authority.preparation_hash,
        authority.package["reviewCandidateDescriptorHash"],
        authority.descriptor["operationHash"], authority.candidate_sha256,
        False, bundle_hash)
    observed = (
        value.get("schemaVersion"), value.get("kind"),
        value.get("preparationHash"), value.get("candidateDescriptorHash"),
        value.get("operationHash"), value.get("candidateCompositeSha256"),
        value.get("operatorAuditionIncluded"), digest(value))
    if observed != expected:
        raise CandidateQcContractError("automated QC bundle is stale")
    for lane in _LANES:
        item = value.get(lane)
        if not isinstance(item, dict):
            raise CandidateQcContractError(f"{lane} bundle item is absent")
        require_keys(item, _ITEM_KEYS, _ITEM_KEYS, f"{lane} bundle item")
        receipt = item.get("receipt")
        if not isinstance(receipt, dict) \
                or item.get("status") != "bounded-pass" \
                or item.get("receiptHash") != digest(receipt) \
                or item.get("candidateCompositeSha256") \
                != authority.candidate_sha256 \
                or receipt.get("status") != "bounded-pass" \
                or receipt.get("operationHash") \
                != authority.descriptor["operationHash"] \
                or receipt.get("candidateCompositeSha256") \
                != authority.candidate_sha256:
            raise CandidateQcContractError(f"{lane} bundle item is stale")
        if lane == "seam":
            _validate_seam_authority(authority, receipt)
    require_hash(value.get("toolManifestHash"), "bundle tool manifest hash")


def load_automated_qc_bundle(
    producer: str,
    preparation_hash: str,
) -> tuple[dict, str, str]:
    """Reopen the sole immutable passing bundle for one preparation."""
    authority = load_candidate_authority(producer, preparation_hash)
    pointer_path = _pointer_path(authority.producer, preparation_hash)
    pointer, _ = _read_json(pointer_path, "automated QC pointer")
    require_keys(pointer, _POINTER_KEYS, _POINTER_KEYS, "automated QC pointer")
    bundle_hash = require_hash(
        pointer.get("bundleHash"), "automated QC bundle hash")
    expected = (
        1, "cut-repair-automated-qc-pointer", preparation_hash,
        authority.package["reviewCandidateDescriptorHash"],
        authority.candidate_sha256)
    observed = (
        pointer.get("schemaVersion"), pointer.get("kind"),
        pointer.get("preparationHash"), pointer.get("candidateDescriptorHash"),
        pointer.get("candidateCompositeSha256"))
    if observed != expected:
        raise CandidateQcContractError("automated QC pointer is stale")
    bundle_path = os.path.join(
        _object_directory(authority.producer), f"{bundle_hash}.json")
    value, raw_hash = _read_json(bundle_path, "automated QC bundle")
    if raw_hash != bundle_hash:
        raise CandidateQcContractError("automated QC object digest is stale")
    _validate_bundle(value, authority, bundle_hash)
    return value, bundle_hash, bundle_path
