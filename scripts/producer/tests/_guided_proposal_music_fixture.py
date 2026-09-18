"""Pure TEST V7 metadata; no source execution, rights, approval or acoustic proof."""
from __future__ import annotations

from copy import deepcopy

from _guided_proposal_reframe_fixture import accepted, candidate, operation, packet
from guided_proposal_music import guided_music_policy


def music_manifest() -> dict:
    """Represent admitted-row metadata, not a fabricated successful decoder call."""
    return {"music": [{"id": "TEST-bed", "path": "/TEST/snapshot.media", "originalPath": "/TEST/bed.wav",
        "source": "library", "licensed": None, "duration": 12.5, "sourceSha256": "a" * 64,
        "sourceSizeBytes": 128, "admissionReceiptPath": ".sniper-external-media/receipts/TEST.json",
        "admissionReceiptSha256": "b" * 64}]}


def music_operation() -> dict:
    """Keep the actual V7 nullable fields and one original operation index."""
    result = operation("music-bed-full-program")
    result["reason"] = "Use the explicitly requested admitted TEST bed for the full program."
    result["music"] = {"schemaVersion": 1, "assetId": "TEST-bed", "gapDb": 11, "duck": True}
    return result


def values(crop: bool = False, music: bool = True) -> tuple[dict, dict, dict, dict]:
    """Build separate held accepted/candidate/proposal/manifest objects."""
    plan, request, manifest = accepted(), packet(), music_manifest()
    plan["target"]["music"] = True
    if not crop:
        plan["target"].update(mode="longform", width=1920, height=1080)
    result = candidate(plan) if crop else deepcopy(plan)
    request["proposal"]["schemaVersion"] = 7
    rows = request["proposal"]["operations"] if crop else [operation("preserve-cut")]
    request["proposal"]["operations"] = [{**row, "music": None} for row in rows]
    if music:
        request["proposal"]["operations"].insert(0, music_operation())
        result["music"] = {"enabled": True, "assetId": "TEST-bed", "gapDb": 11, "duck": True}
    raw = "Use the exact admitted TEST bed." if music else "Keep the accepted music state."
    if crop:
        raw += " Use the exact crop and caption every kept word."
    request["rawRequest"]["rawIntent"] = raw
    clause = request["proposal"]["clauses"][0]
    clause.update(start=0, end=len(raw), quote=raw, operationIndices=list(range(len(request["proposal"]["operations"]))))
    request["evidence"] = {"schemaVersion": 7, "musicPolicy": guided_music_policy(plan, manifest)}
    return plan, result, request, manifest


def source_entry(row: dict) -> dict:
    """The real source-set uses timed-media, not an invented audio mediaKind."""
    return {"lane": "music", "mediaKind": "timed-media", "originalPath": row["originalPath"],
        "snapshotPath": row["path"], "sha256": row["sourceSha256"], "sizeBytes": row["sourceSizeBytes"],
        "admissionReceiptPath": row["admissionReceiptPath"], "admissionReceiptSha256": row["admissionReceiptSha256"]}
