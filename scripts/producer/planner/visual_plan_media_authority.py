"""Validate controller-frozen media and its bounded source-set receipt."""
from __future__ import annotations

import hashlib
import json
import os

from headless.admission_receipt import (
    AdmissionReceiptError, validate_admission_receipt,
)
from planner.visual_plan_fields import (
    VisualPlanContractError, id_field, object_field, path_field, sha_field,
)
from planner.visual_plan_file_pins import MAX_EVIDENCE_BYTES, read_json_pin, verify_file

MAX_SOURCE_ITEMS = 64
MAX_SUPPORTING_ITEMS = 128
MAX_SOURCE_SET_ITEMS = 256
SOURCE_SET_POLICY = "sniper-producer-source-set-v1"
_MODALITIES = {"source-footage", "supplied-broll", "external-media"}
_LANES = {"source", "broll", "external", "music"}
_SPECS = (
    ("sources", "source-footage", "source", MAX_SOURCE_ITEMS, True),
    ("broll", "supplied-broll", "broll", MAX_SUPPORTING_ITEMS, False),
    ("externalMedia", "external-media", "external", MAX_SUPPORTING_ITEMS, False),
)


def validate_media_document(plan: dict, document: dict) -> dict:
    """Rebuild manifest/receipt inventory and return its stable identity map."""
    project = object_field(
        document["project"], "media authority project",
        {"acceptedProgramSha256", "transcriptSha256"}, set())
    expected_project = {key: plan["project"][key] for key in project}
    if document["schemaVersion"] != 1 \
            or document["kind"] != "visual-plan-media-authority" \
            or project != expected_project:
        raise VisualPlanContractError(
            "media authority differs from the accepted program")
    manifest_pin = _manifest_pin(document["manifest"])
    manifest = read_json_pin(
        manifest_pin, "media authority manifest", MAX_EVIDENCE_BYTES)
    if not isinstance(manifest, dict):
        raise VisualPlanContractError("media authority manifest must be an object")
    root = os.path.dirname(os.path.realpath(manifest_pin["path"]))
    source_set, entries = _source_set(manifest, root)
    expected = _manifest_inventory(manifest, root, entries)
    actual = _document_inventory(document)
    if document["sourceSetAdmission"] != source_set:
        raise VisualPlanContractError(
            "media authority source-set binding differs from its manifest")
    if document["inventoryCount"] != len(actual) or actual != expected:
        raise VisualPlanContractError(
            "media authority inventory differs from its admitted source set")
    keys = [(row["modality"], row["recordId"]) for row in actual]
    if len(keys) != len(set(keys)):
        raise VisualPlanContractError("media authority identities are duplicated")
    return {key: row for key, row in zip(keys, actual)}


def _manifest_pin(value: object) -> dict:
    row = object_field(value, "media authority manifest", {"path", "sha256"}, set())
    path_field(row["path"], "media authority manifest path")
    sha_field(row["sha256"], "media authority manifest sha256")
    return row


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True, allow_nan=False) + "\n").encode("ascii")


def _source_set_digest(entries: list[dict]) -> str:
    return hashlib.sha256(
        b"sniper-producer-source-set-v1\0" + _canonical_bytes(entries)).hexdigest()


def _source_set(manifest: dict, root: str) -> tuple[dict, list[dict]]:
    binding = object_field(
        manifest.get("sourceSetAdmission"), "manifest source-set admission",
        {"schemaVersion", "receiptPath", "receiptSha256", "sourceSetDigest",
         "entryCount"}, set())
    receipt_sha = sha_field(binding["receiptSha256"], "source-set receipt sha256")
    digest = sha_field(binding["sourceSetDigest"], "source-set digest")
    relative = f".sniper-source-sets/{receipt_sha}.json"
    if binding["schemaVersion"] != 1 or binding["receiptPath"] != relative \
            or type(binding["entryCount"]) is not int \
            or not 1 <= binding["entryCount"] <= MAX_SOURCE_SET_ITEMS:
        raise VisualPlanContractError("manifest source-set admission is malformed")
    receipt_path = os.path.join(root, ".sniper-source-sets", f"{receipt_sha}.json")
    receipt = read_json_pin(
        {"path": receipt_path, "sha256": receipt_sha},
        "source-set receipt", MAX_EVIDENCE_BYTES)
    receipt = object_field(
        receipt, "source-set receipt",
        {"schemaVersion", "policy", "entries", "sourceSetDigest"}, set())
    entries = receipt["entries"]
    if receipt["schemaVersion"] != 1 or receipt["policy"] != SOURCE_SET_POLICY \
            or not isinstance(entries, list) or len(entries) != binding["entryCount"]:
        raise VisualPlanContractError(
            "source-set receipt differs from its manifest binding")
    verified = [_source_set_entry(row, root) for row in entries]
    ordered = sorted(verified, key=lambda row: (row["lane"], row["originalPath"]))
    expected_digest = _source_set_digest(ordered)
    if verified != ordered or receipt["sourceSetDigest"] != expected_digest \
            or digest != expected_digest:
        raise VisualPlanContractError("source-set receipt digest or ordering is stale")
    return ({"schemaVersion": 1, "receiptPath": receipt_path,
             "receiptSha256": receipt_sha, "sourceSetDigest": expected_digest,
             "entryCount": len(verified)}, verified)


def _source_set_entry(value: object, root: str) -> dict:
    required = {"lane", "originalPath", "snapshotPath", "sha256", "sizeBytes",
                "mediaKind", "admissionReceiptPath", "admissionReceiptSha256"}
    row = object_field(
        value, "source-set entry", required, {"authorizationEvidence"})
    receipt_sha = sha_field(
        row["admissionReceiptSha256"], "source-set admission receipt sha256")
    relative = f".sniper-external-media/receipts/{receipt_sha}.json"
    snapshot = row["snapshotPath"]
    if row["lane"] not in _LANES or not os.path.isabs(row["originalPath"]) \
            or not isinstance(snapshot, str) or not os.path.isabs(snapshot) \
            or os.path.basename(snapshot) != f"{row['sha256']}.media" \
            or os.path.basename(os.path.dirname(snapshot)) != ".sniper-external-media" \
            or os.path.realpath(os.path.dirname(os.path.dirname(snapshot))) != root \
            or row["admissionReceiptPath"] != relative \
            or type(row["sizeBytes"]) is not int or row["sizeBytes"] < 0 \
            or not isinstance(row["mediaKind"], str) or not row["mediaKind"]:
        raise VisualPlanContractError("source-set entry identity is malformed")
    sha_field(row["sha256"], "source-set snapshot sha256")
    expected = os.path.join(
        root, ".sniper-external-media", "receipts", f"{receipt_sha}.json")
    if os.path.abspath(os.path.join(root, relative)) != expected:
        raise VisualPlanContractError("source-set admission receipt path escaped")
    _validate_admission_receipt(row, expected, receipt_sha)
    modality = "external-media" if row["lane"] == "external" else row["lane"]
    _authorization_evidence(row, modality, row["sha256"], root)
    return row


def _validate_admission_receipt(entry: dict, path: str, sha256: str) -> None:
    receipt = read_json_pin(
        {"path": path, "sha256": sha256}, "media admission receipt",
        MAX_EVIDENCE_BYTES)
    try:
        _limits, decoded = validate_admission_receipt(receipt)
    except AdmissionReceiptError as exc:
        raise VisualPlanContractError(
            "media admission receipt lacks approved decode evidence") from exc
    snapshot = receipt.get("snapshot") if isinstance(receipt, dict) else None
    facts = decoded.get("facts") if isinstance(decoded, dict) else None
    expected = {"path": entry["snapshotPath"], "sha256": entry["sha256"],
                "sizeBytes": entry["sizeBytes"]}
    if not isinstance(snapshot, dict) or any(
            snapshot.get(key) != value for key, value in expected.items()) \
            or not isinstance(facts, dict) \
            or facts.get("sizeBytes") != entry["sizeBytes"] \
            or facts.get("mediaKind") != entry["mediaKind"]:
        raise VisualPlanContractError(
            "media admission receipt differs from its source-set entry")


def _manifest_inventory(manifest: dict, root: str,
                        entries: list[dict]) -> list[dict]:
    rows = []
    for key, modality, lane, maximum, required in _SPECS:
        values = manifest.get(key, [])
        if not isinstance(values, list) or len(values) > maximum \
                or (required and not values):
            raise VisualPlanContractError(f"media manifest {key} bounds are invalid")
        rows.extend(_manifest_item(value, modality, lane, root, entries)
                    for value in values)
    rows.sort(key=lambda row: (row["modality"], row["recordId"]))
    receipts = [(row["sourceSetLane"], row["originalPath"]) for row in rows]
    if len(receipts) != len(set(receipts)):
        raise VisualPlanContractError("media manifest reuses one source-set entry")
    return rows


def _manifest_item(value: object, modality: str, lane: str,
                   root: str, entries: list[dict]) -> dict:
    if not isinstance(value, dict):
        raise VisualPlanContractError(f"{modality} manifest row must be an object")
    record_id = id_field(value.get("id"), f"{modality} manifest ID")
    raw_path = path_field(value.get("path"), f"{modality} manifest path")
    source_sha = sha_field(
        value.get("sourceSha256"), f"{modality} manifest source hash")
    original = path_field(
        value.get("originalPath"), f"{modality} manifest original path")
    receipt_sha = sha_field(value.get("admissionReceiptSha256"),
                            f"{modality} admission receipt hash")
    relative = f".sniper-external-media/receipts/{receipt_sha}.json"
    absolute = os.path.abspath(os.path.join(root, raw_path))
    match = next((row for row in entries if row["lane"] == lane
                  and row["originalPath"] == original
                  and row["snapshotPath"] == absolute
                  and row["sha256"] == source_sha
                  and row["admissionReceiptPath"] == value.get("admissionReceiptPath")
                  and row["admissionReceiptSha256"] == receipt_sha), None)
    if not os.path.isabs(original) or value.get("admissionReceiptPath") != relative \
            or match is None:
        raise VisualPlanContractError(
            f"{modality} manifest row is absent from source-set receipt")
    if value.get("authorizationEvidence") != match.get("authorizationEvidence"):
        raise VisualPlanContractError(
            f"{modality} manifest authorization differs from its source-set receipt")
    authorization = _authorization_evidence(
        match, modality, source_sha, root)
    return {"modality": modality, "recordId": record_id, "path": absolute,
            "sourceSha256": source_sha, "sourceSetLane": lane,
            "originalPath": original,
            "sourceSetEvidence": {
                "path": os.path.abspath(os.path.join(root, relative)),
                "sha256": receipt_sha},
            "authorizationEvidence": authorization}


def _authorization_evidence(value: dict, modality: str,
                            source_sha: str, root: str) -> dict | None:
    raw = value.get("authorizationEvidence")
    if raw is None:
        return None
    if modality != "external-media":
        raise VisualPlanContractError(
            "only external media may carry authorization evidence")
    pin = object_field(
        raw, "external-media authorization evidence", {"path", "sha256"}, set())
    path_field(pin["path"], "external-media authorization path")
    sha_field(pin["sha256"], "external-media authorization hash")
    evidence = {**pin, "path": os.path.abspath(os.path.join(root, pin["path"]))}
    document = read_json_pin(
        evidence, "external-media authorization receipt", MAX_EVIDENCE_BYTES)
    document = object_field(
        document, "external-media authorization receipt",
        {"schemaVersion", "kind", "assetFile", "record", "acquisition"}, set())
    record = document["record"]
    rights = record.get("rights") if isinstance(record, dict) else None
    allowed_uses = rights.get("allowedUses") if isinstance(rights, dict) else None
    platforms = rights.get("allowedPlatforms") if isinstance(rights, dict) else None
    if document["schemaVersion"] != 1 \
            or document["kind"] != "native-short-asset-origin" \
            or not isinstance(record, dict) or record.get("sha256") != source_sha \
            or record.get("publicationDisposition") not in {"approved", "needs-review"} \
            or not isinstance(allowed_uses, list) or "editorial" not in allowed_uses \
            or not isinstance(platforms, list) or "local-review" not in platforms \
            or not isinstance(document["acquisition"], dict):
        raise VisualPlanContractError(
            "external-media authorization receipt is not eligible for local review")
    return evidence


def _document_inventory(document: dict) -> list[dict]:
    inventory = document["inventory"]
    if not isinstance(inventory, list) or len(inventory) > \
            MAX_SOURCE_ITEMS + MAX_SUPPORTING_ITEMS * 2:
        raise VisualPlanContractError("media authority inventory exceeds its bound")
    return [_inventory_item(value, index)
            for index, value in enumerate(inventory)]


def _inventory_item(value: object, index: int) -> dict:
    required = {"modality", "recordId", "path", "sourceSha256",
                "sourceSetLane", "originalPath", "sourceSetEvidence",
                "authorizationEvidence"}
    row = object_field(value, f"media authority inventory {index}", required, set())
    if row["modality"] not in _MODALITIES or row["sourceSetLane"] not in _LANES:
        raise VisualPlanContractError("media authority modality or lane is invalid")
    id_field(row["recordId"], f"media authority inventory {index} recordId")
    path_field(row["path"], f"media authority inventory {index} path")
    sha_field(row["sourceSha256"],
              f"media authority inventory {index} sourceSha256")
    path_field(row["originalPath"],
               f"media authority inventory {index} originalPath")
    evidence = object_field(
        row["sourceSetEvidence"], "media authority source-set evidence",
        {"path", "sha256"}, set())
    path_field(evidence["path"], "media authority source-set evidence path")
    sha_field(evidence["sha256"], "media authority source-set evidence hash")
    authorization = row["authorizationEvidence"]
    if authorization is not None:
        authorization = object_field(
            authorization, "media authority authorization evidence",
            {"path", "sha256"}, set())
        path_field(authorization["path"], "media authority authorization path")
        sha_field(authorization["sha256"], "media authority authorization hash")
    return row
