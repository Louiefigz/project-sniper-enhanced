"""Pure full-body clearance/picture links, never execution or approval authority.

Live callers authenticate the actual returned proof before calling this
projector. Cold callers authenticate the stopped worker and independently
reconstruct the full graph, report and original pages. Hashes alone do neither.
"""
from __future__ import annotations

from copy import deepcopy

from cut_preview_io import digest
from guided_opening_inputs import closed, hash_value
from guided_presenter_caption_clearance import POLICY
from opening_prefix_contract import canonical_hash

ORIGINAL_PROOF_FIELDS = frozenset({"schemaVersion", "kind", "scope", "outputPath", "output",
    "executedCommandHash", "ordinaryPathCommandHash", "outputTransport", "privateMoovPlacement",
    "prefixOracle", "elapsedMs", "outputDecoded", "audioCompared", "deliveryApproved", "cleanupScope"})


def validate_original_body_picture_proof(proof: dict) -> None:
    """Close only the actual unaugmented shared compositor return, not its provenance."""
    closed(proof, ORIGINAL_PROOF_FIELDS, "original body presenter picture proof")
    expected = {"schemaVersion": 2, "kind": "verified-presenter-prefix-private-picture-composition",
        "scope": "executed-graph-bound-picture-not-decoded-output-or-approval",
        "outputTransport": "exclusively-reserved-held-regular-file-descriptor-mp4",
        "privateMoovPlacement": "end-of-file; faststart belongs to existing final delivery mux",
        "outputDecoded": False, "audioCompared": False, "deliveryApproved": False,
        "cleanupScope": "owned-runner-local-groups; caller-must-reconcile-external-ledger"}
    if any(type(proof[key]) is not type(value) or proof[key] != value for key, value in expected.items()):
        raise RuntimeError("original body presenter picture proof changed its closed class")
    for key in ("executedCommandHash", "ordinaryPathCommandHash"):
        hash_value(proof[key])
    closed(proof["output"], {"path", "sha256", "size_bytes"}, "body picture output")
    output = proof["output"]
    hash_value(output["sha256"])
    if type(output["path"]) is not str or output["path"] != proof["outputPath"] \
            or type(output["size_bytes"]) is not int or not 0 < output["size_bytes"] <= 2 * 1024 ** 3:
        raise RuntimeError("body picture output lacks its exact bounded identity")


def _links(report: dict, proof: dict, retained: dict, pages: tuple[dict, ...]) -> dict:
    """Require full coverage and unchanged unapproved observations before projection."""
    validate_original_body_picture_proof(proof)
    if type(report) is not dict or report.get("kind") != "presenter-caption-clearance" \
            or report.get("policy") != POLICY or report.get("state") not in ("screened-no-overlap", "not-applicable") \
            or any(report.get(key) is not False for key in ("pictureProofBound", "qcPassed", "creativeApproved", "deliveryApproved")):
        raise RuntimeError("body picture needs its unchanged precomposition clearance report")
    binding, oracle = report["binding"], proof["prefixOracle"]
    if binding["coverage"] != {"startFrame": 0, "endFrameExclusive": binding["clock"]["totalFrames"]} \
            or type(pages) is not tuple or not pages \
            or oracle.get("schemaVersion") != 2 or oracle.get("kind") != "presenter-compositor-prefix-oracle" \
            or oracle.get("status") != "verified" \
            or oracle.get("layerPolicy", {}).get("fullCaptionTail") != len(pages):
        raise RuntimeError("body clearance lacks whole-program coverage or original full caption tail")
    hash_value(oracle["fullGraphHash"])
    closed(retained, {"path", "sha256", "sizeBytes"}, "retained body picture")
    output = proof["output"]
    if type(retained["path"]) is not str or retained["path"] == output["path"] \
            or type(retained["sizeBytes"]) is not int or retained["sizeBytes"] != output["size_bytes"] \
            or retained["sha256"] != output["sha256"]:
        raise RuntimeError("retained body picture differs from actual returned output bytes")
    return binding


def body_presenter_caption_picture_record(report: dict, proof: dict,
                                         retained: dict, pages: tuple[dict, ...]) -> dict:
    """Project independently authenticated evidence; do not promote it to QC or approval."""
    binding = _links(report, proof, retained, pages)
    return {"schemaVersion": 1, "kind": "presenter-caption-body-picture-clearance-binding",
        "scope": "actual-full-body-picture-bound-manual-envelope-not-qc-or-approval",
        "executionInputHash": binding["executionInputHash"], "candidatePlanHash": binding["candidatePlanHash"],
        "authorityHash": binding["authorityHash"], "coverage": deepcopy(binding["coverage"]),
        "captionProjectionHash": binding["captionProjectionHash"], "fullCaptionTail": len(pages),
        "fullCaptionPageGraphHash": digest(list(pages)), "fullCombinedGraphHash": proof["prefixOracle"]["fullGraphHash"],
        "fullPresenterGraphHash": binding["presenterGraphHash"], "prefixOracleHash": digest(proof["prefixOracle"]),
        "compositionProofHash": digest(proof), "output": deepcopy(proof["output"]),
        "retainedPicture": deepcopy(retained), "precompositionReport": deepcopy(report),
        "precompositionReportHash": canonical_hash(report), "pictureEvidenceBound": True,
        "qcPassed": False, "creativeApproved": False, "deliveryApproved": False}
