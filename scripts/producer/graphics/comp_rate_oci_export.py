"""Export a compact OCI receipt only after deep audit of real retained evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash, write_new
from graphics.comp_rate_oci_artifact import CHECKS, CLAIM, ROOT, SCOPE, validate_oci_receipt
from graphics.comp_rate_oci_audit import _current, audit


def _relative_rows(rows: list[dict]) -> list[dict]:
    """Retain exact source identities without publishing machine-local source paths."""
    result = [{"path": str(Path(row["path"]).relative_to(ROOT)), "sha256": row["sha256"]} for row in rows]
    return sorted(result, key=lambda row: row["path"])


def _audit_sources() -> list[dict]:
    """Bind the audited reader/exporter code separately from startup execution."""
    names = ("comp_rate_oci_artifact.py", "comp_rate_oci_audit.py", "comp_rate_oci_export.py", "comp_rate_oci_inventory.py")
    rows = [{"path": str(Path(__file__).with_name(name)), "sha256": file_hash(Path(__file__).with_name(name))}
            for name in names]
    return _relative_rows(rows)


def _runner_observation(root: Path) -> dict:
    """Do not promote a mid-run source observation into a startup attestation."""
    value = bound_json(root / "runner-observation.json")
    actual = file_hash(root / "runner-observed-after-start.py")
    if value["runnerStartupCapture"] != "unavailable" or value["sha256"] != actual:
        raise RuntimeError("runner observation is inconsistent or claims unavailable startup proof")
    return {"startupCapture": "unavailable", "observedAfterStartSha256": actual}


def _compact_rows(raw: dict, inputs: dict) -> list[dict]:
    """Preserve measured hashes/facts; add only explicit deep-audited bindings."""
    requests = {(row["kind"], row["rate"]): row for row in inputs["requests"]}
    keys = ("kind", "rate", "duration", "stream", "mediaSha256", "inputSha256",
            "runtimeReceiptSha256", "decoded", "elapsedMs")
    rows = []
    for row in raw["probes"]:
        request = requests[(row["kind"], row["rate"])]
        rows.append({**{key: row[key] for key in keys}, "sourceSha256": request["sourceSha256"],
                     "specHash": request["specHash"], "checks": CHECKS})
    return sorted(rows, key=lambda row: (row["kind"], row["rate"]))


def _compact(raw: dict, inputs: dict, root: Path) -> dict:
    """Construct a runtime-specific receipt that never claims private availability."""
    header = raw["inputs"]
    return {"schemaVersion": 2, "kind": "hyperframes-oci-released-rate-matrix", "runtimeScope": SCOPE,
            "passed": True, "qualityClaim": CLAIM, "sourceDigest": header["sourceDigest"],
            "capabilityDigest": header["capabilityDigest"], "compositionCount": len(header["compositionKinds"]),
            "rates": header["rates"], "probeFrames": header["probeFrames"], "imageId": raw["imageId"],
            "renderToolClosure": raw["renderToolClosure"], "proofTools": raw["proofTools"],
            "executionSources": _relative_rows(header["sourceEpoch"]["files"]),
            "rawEvidence": {"receiptHash": raw["receiptHash"], "inputsSha256": file_hash(root / "inputs.json"),
                            "auditSources": _audit_sources(), "checks": CHECKS,
                            "privateEvidenceRequiredForDeepRevalidation": True},
            "runnerObservation": _runner_observation(root), "probes": _compact_rows(raw, inputs),
            "elapsedMs": raw["elapsedMs"]}


def export_receipt(directory: Path, destination: Path) -> dict:
    """Deep-audit the actual private cohort, then write one new compact artifact."""
    root = directory.resolve(strict=True)
    audit_sources = _audit_sources()
    audited = audit(root)
    raw = bound_json(root / "matrix.json", audited["rawFileSha256"])
    inputs = bound_json(root / "inputs.json", audited["inputsFileSha256"])
    if raw["receiptHash"] != audited["rawReceiptHash"]:
        raise RuntimeError("cohort changed after deep audit")
    value = _compact(raw, inputs, root)
    value["receiptHash"] = digest(value)
    issue = validate_oci_receipt(value, value["receiptHash"], raw["proofTools"])
    if issue:
        raise RuntimeError(issue)
    _current(raw, inputs)
    bound_json(root / "matrix.json", audited["rawFileSha256"])
    bound_json(root / "inputs.json", audited["inputsFileSha256"])
    if _audit_sources() != audit_sources:
        raise RuntimeError("OCI exporter/auditor closure changed during export")
    write_new(destination, value)
    return {"out": str(destination), "receiptHash": value["receiptHash"], "probes": len(value["probes"]),
            "reviewStatus": "exported for review; not automatically selected as current proof"}


def main() -> None:
    """Require explicit private evidence and a new caller-chosen destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(export_receipt(Path(args.directory), Path(args.out)), sort_keys=True))


if __name__ == "__main__":
    main()
