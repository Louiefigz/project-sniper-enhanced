"""Fourteen real JSON documents over TEST sentinel admission, never creator consent.

Only the decoder/probe are fake. The real ingest source-set writer, bounded
document reader and source-byte verification are exercised without any media.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from _guided_proposal_music_fixture import values
from _ingest_admission_fixture import probe, runner
from cut_preview_authority import REQUEST_HASHES
from cut_preview_io import digest, file_hash, write_new
from edit.compatibility_projection import build_projection
from cross_runtime_canonical_json import canonical_compact_json
from guided_media_profile import OPENING_PROFILE
from guided_opening_inputs import OpeningInputs, read_current_inputs
from guided_proposal_music import guided_music_policy
import ingest

HASH = "a" * 64


def raw_hash(value: dict) -> str:
    """Match exact new-only document transport, not merely semantic object hashes."""
    return hashlib.sha256((canonical_compact_json(value) + "\n").encode()).hexdigest()


def admitted_values(root: Path) -> tuple[dict, dict, dict, dict]:
    """Create only private TEST sentinel assets and a real retained admission tree."""
    incoming, output = root / "incoming", root / "documents"
    incoming.mkdir()
    (incoming / "music").mkdir()
    (incoming / "take.mp4").write_bytes(b"TEST NOT MEDIA source")
    (incoming / "music/bed.wav").write_bytes(b"TEST NOT MEDIA music")
    with patch("ingest_admission.admit_external_media", side_effect=runner), \
            patch("ingest_admitted_sources.probe_media", side_effect=probe), \
            patch("ingest_admitted_scan.probe_media", side_effect=probe), \
            patch("ingest.scan_builtin_music", return_value=[]), redirect_stdout(io.StringIO()):
        manifest = ingest.build_manifest(incoming, output, no_transcribe=True)
    plan, result, packet, _ = values()
    plan["cutTrack"] = [{"sourceId": manifest["sources"][0]["id"], "start": 0, "end": 1, "speed": 1}]
    result["cutTrack"] = deepcopy(plan["cutTrack"])
    asset = manifest["music"][0]["id"]
    result["music"]["assetId"] = packet["proposal"]["operations"][0]["music"]["assetId"] = asset
    packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
    return plan, result, packet, manifest


def _cut_documents(plan: dict, manifest: dict) -> dict:
    """Use actual compatibility projection and exact raw cut-parent references."""
    projection = build_projection(plan, digest(plan))
    request = {key: HASH for key in REQUEST_HASHES}
    request.update(schemaVersion=1, createdAt="2026-09-07T00:00:00.000Z", planHash=raw_hash(plan),
        timelineMapHash=projection["timelineMapHash"], projectionReceiptHash=raw_hash(projection))
    lock = {key: request[key] for key in ("cutAuthorityDigest", "cutApprovalReceiptHash",
        "cutReviewApprovalReceiptHash", "timelineMapHash", "projectionReceiptHash")}
    lock.update(approvedCutPlanHash=digest(plan), manifestHash=raw_hash(manifest))
    request["pictureLockHash"] = raw_hash(lock)
    request["requestHash"] = digest({key: item for key, item in request.items() if key != "requestHash"})
    return {"acceptedPlan": plan, "manifest": manifest, "cutRequest": request, "pictureLock": lock,
        "cutProjection": projection, "timelineMap": projection["timelineMap"]}


def _readiness_documents(result: dict, supplied: dict) -> dict:
    """Close actual reader relationships with explicitly TEST-only non-executable packets."""
    packet = deepcopy(supplied)
    occurrence = {"anchors": [0, 30], "occurrences": [], "segments": []}
    bindings = {"schemaVersion": 1, "frameRate": "30/1", "totalFrames": 30, "graphics": []}
    packet.update(proposalHash=digest(packet["proposal"]), clockHash=HASH,
        generationStartedAt="2026-09-07T00:00:00.000Z", cutDecisionHash=HASH,
        parentRevisionHash=HASH, treatmentAdmissionHash=HASH, candidate=result,
        executionBindings=bindings, range={"approval": {"startFrame": 0, "endFrame": 15},
                                          "review": {"startFrame": 0, "endFrame": 30}})
    packet["evidence"].update(frameRate="30/1", totalFrames=30, **occurrence)
    draft = {"workflowState": "TREATMENT_DRAFT", "schemaVersion": 2,
             "planObjectHash": digest(result), "parentRevisionHash": HASH}
    bundle = {"verdict": "clean", "executable": False, "TEST_ONLY": "Not an actual critic or user approval"}
    receipt = {"kind": "guided-proposal-readiness", "executable": False, "packetHash": digest(packet),
        "reviewBundleHash": digest(bundle), "treatmentDraftRevisionHash": digest(draft)}
    return {"candidatePlan": result, "frameBindings": bindings, "occurrences": occurrence,
        "readinessPacket": packet, "treatmentDraft": draft, "readinessBundle": bundle, "readinessReceipt": receipt}


def _authority(docs: dict) -> dict:
    """Build the existing exact authority shape; values remain TEST metadata only."""
    packet, request = docs["readinessPacket"], docs["cutRequest"]
    return {"schemaVersion": 2, "kind": "guided-opening-media-authority", "profile": OPENING_PROFILE,
        "scope": "private-opening-execution-not-opening-approval-body-or-delivery",
        "runId": "TEST-metadata-only", "previewAttempt": 1, "contextHash": HASH,
        "cutDecisionHash": HASH, "acceptedRevisionHash": HASH, "requestHash": request["requestHash"],
        "pictureLockHash": request["pictureLockHash"], "projectionHash": request["projectionReceiptHash"],
        "sourceSetDigest": docs["manifest"]["sourceSetAdmission"]["sourceSetDigest"],
        "manifestHash": raw_hash(docs["manifest"]), "timelineMapHash": request["timelineMapHash"],
        "rawAdmissionHash": HASH, "proposalHash": packet["proposalHash"],
        "readinessHash": digest(docs["readinessReceipt"]), "draftRevisionHash": digest(docs["treatmentDraft"]),
        "candidatePlanHash": digest(docs["candidatePlan"]), "frameBindingsHash": digest(docs["frameBindings"]),
        "occurrenceEvidenceHash": digest(docs["occurrences"]), "clockHash": HASH,
        "generationStartedAt": packet["generationStartedAt"], "frameRate": "30/1", "totalFrames": 30,
        "target": docs["acceptedPlan"]["target"], "core": packet["range"]["approval"], "review": packet["range"]["review"]}


def publish(root: Path, rows: tuple[dict, dict, dict, dict]) -> tuple[Path, str]:
    """Publish only new private documents; no selected project or old receipt is touched."""
    plan, result, packet, manifest = rows
    docs = {**_cut_documents(plan, manifest), **_readiness_documents(result, packet)}
    docs["authority"] = _authority(docs)
    refs = {}
    for name, value in docs.items():
        path = root / "documents" / f"{name}.json"
        write_new(path, value)
        refs[name] = {"path": str(path), "sha256": file_hash(path)}
    value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": str(uuid4()),
        "profile": OPENING_PROFILE, "documents": refs, "pipeline": {}}
    value["executionInputHash"] = digest(value)
    path = root / "documents/input.json"
    write_new(path, value)
    return path, file_hash(path)


def read(root: Path, rows: tuple[dict, dict, dict, dict]) -> OpeningInputs:
    """Call the real fourteen-document reader and source-byte gate, with no stubs."""
    return read_current_inputs(*publish(root, rows))
