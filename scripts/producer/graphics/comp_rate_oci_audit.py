"""Offline deep audit of a completed private OCI rate cohort, without renders.

This is an evidence reader, not a release selector or approval mechanism. It
requires the original per-probe media, sealed inputs, and runtime attestations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash, read_bytes
from graphics.comp_capability_artifact import capability_digest, capability_row_issue
from graphics.comp_catalog_probe import probe_spec
from graphics.comp_rate_artifact import RELEASED_RATES, _duration_for, _stream_issue
from graphics.comp_rate_oci import proof_tools, validate_completed
from graphics.comp_rate_oci_inputs import MOTION_DIR, qualified_catalog, source_epoch
from graphics.comp_rate_oci_inventory import required_execution_paths
from graphics.template_contract import declared_variables
from headless.container_io import CompositionInput, _manifest, _source_entries, verify_snapshot_archive
from headless.runtime_receipt import _validate as validate_runtime_shape


def _sha(data: bytes) -> str:
    """Hash exact source/JSON bytes without decoding or normalization."""
    return hashlib.sha256(data).hexdigest()


def _current(value: dict, inputs: dict) -> dict:
    """Require the current catalog, policy, and separate proof-decoder epoch."""
    capabilities, _ = qualified_catalog()
    if any(capability_row_issue(row) for row in capabilities.values()):
        raise RuntimeError("current capability rows are not released")
    header = value["inputs"]
    if inputs["header"] != header or header["compositionKinds"] != sorted(capabilities):
        raise RuntimeError("cohort inputs do not bind the current catalog")
    root = Path(__file__).resolve().parents[3]
    paths = {Path(row["path"]) for row in header["sourceEpoch"]["files"]}
    if paths != required_execution_paths(root, inputs["requests"]) or len(paths) != len(header["sourceEpoch"]["files"]):
        raise RuntimeError("cohort captured implementation/dependency inventory is incomplete")
    if any(not path.is_relative_to(root) or path.resolve(strict=True) != path for path in paths):
        raise RuntimeError("cohort source paths escape the repository")
    if source_epoch(paths) != header["sourceEpoch"]:
        raise RuntimeError("cohort source/runtime policy changed")
    if header["capabilityDigest"] != capability_digest(capabilities):
        raise RuntimeError("cohort capability digest changed")
    if proof_tools()[1] != value["proofTools"]:
        raise RuntimeError("cohort host proof decoders changed")
    approval = bound_json(Path(__file__).resolve().parents[1] / "headless/render_image_approval.json")
    if value["imageId"] != approval["imageId"] or value["renderToolClosure"] != approval["probedClosure"]:
        raise RuntimeError("cohort approved OCI render closure changed")
    return capabilities


def _request_sources(request: dict) -> None:
    """Bind every archive member to current defaults and exact duration rewrite."""
    kind, rate = request["kind"], request["rate"]
    relative = f"compositions/{kind}.html"
    source = read_bytes(Path(MOTION_DIR) / relative)
    html = source.decode("utf8")
    spec = probe_spec(kind, declared_variables(html))
    duration = _duration_for(rate)
    if request["composition"] != relative or request["duration"] != duration:
        raise RuntimeError("cohort request composition/duration is inconsistent")
    if request["sourceSha256"] != _sha(source) or request["specHash"] != digest(spec):
        raise RuntimeError("cohort request source/defaults changed")
    seconds = Fraction(int(duration["numerator"]), int(duration["denominator"]))
    composition = CompositionInput(relative, html, duration=float(seconds))
    entries, bindings = _source_entries(str(Path(MOTION_DIR).parents[1]), composition, spec)
    if list(bindings) != request["assetBindings"]:
        raise RuntimeError("cohort asset binding differs from current resolved defaults")
    for name, value in (("variables", spec), ("asset-bindings", list(bindings))):
        entries[f"request/{name}.json"] = json.dumps(value, sort_keys=True, ensure_ascii=True,
                                                      separators=(",", ":"), allow_nan=False).encode("ascii")
    if list(_manifest(entries)) != request["manifest"]:
        raise RuntimeError("cohort archive members are not exactly bound to current sources")


def _runtime(row: dict, request: dict, directory: Path, image: str) -> None:
    """Revalidate actual media/archive/runtime identity and exact CLI arguments."""
    media = directory / "probe.mov"
    runtime_path = directory / "probe.mov.runtime.json"
    if file_hash(media) != row["mediaSha256"] or file_hash(runtime_path) != row["runtimeReceiptSha256"]:
        raise RuntimeError("cohort media/runtime receipt bytes changed")
    runtime = bound_json(runtime_path)
    validate_runtime_shape(runtime, row["mediaSha256"])
    if runtime["imageId"] != image or runtime["snapshotSha256"] != row["inputSha256"]:
        raise RuntimeError("cohort row references another render/input")
    if runtime["snapshotManifest"] != request["manifest"] or runtime["containerRemoval"] != row["containerRemoval"]:
        raise RuntimeError("cohort request/removal differs from observed runtime")
    expected = ["render", "/scratch/project/motion", "-c", request["composition"],
                "--format", "mov", "--variables-file", "/scratch/project/request/variables.json",
                "-o", "/output/render.mov", "--fps", row["rate"], "--quality", "high",
                "--workers", "1", "--no-browser-gpu", "--strict", "--strict-variables", "--json"]
    if runtime["containerBeforeOutput"]["Args"] != expected:
        raise RuntimeError("cohort runtime arguments do not match the exact probe")
    archive = verify_snapshot_archive(str(media) + ".input.tar", row["inputSha256"], tuple(request["manifest"]))
    if archive["sizeBytes"] != request["inputSizeBytes"]:
        raise RuntimeError("cohort retained archive size differs from request")


def _rows(value: dict, inputs: dict, root: Path, capabilities: dict) -> None:
    """Reject repeated/missing requests, mismatched streams, or orphaned rows."""
    requests = inputs["requests"]
    pairs = [(row["kind"], row["rate"]) for row in requests]
    expected = {(kind, rate) for kind in capabilities for rate in RELEASED_RATES}
    if len(pairs) != len(expected) or set(pairs) != expected:
        raise RuntimeError("cohort input cross-product repeats or is incomplete")
    lookup = dict(zip(pairs, requests))
    for row in value["probes"]:
        request = lookup[(row["kind"], row["rate"])]
        directory = Path(request["directory"])
        if directory.parent != root or directory.resolve(strict=True) != directory:
            raise RuntimeError("cohort probe directory escapes its private attempt")
        if row["duration"] != request["duration"] or row["inputSha256"] != request["inputSha256"]:
            raise RuntimeError("cohort output is not bound to its exact request")
        if bound_json(directory / "result.json") != row:
            raise RuntimeError("cohort retained row differs from aggregate receipt")
        issue = _stream_issue(row["stream"], row["rate"], capabilities[row["kind"]]["canvas"])
        if issue:
            raise RuntimeError(issue)
        _request_sources(request)
        _runtime(row, request, directory, value["imageId"])


def audit(directory: Path) -> dict:
    """Read a complete real cohort; never replace evidence or launch a worker."""
    root = directory.resolve(strict=True)
    raw_hash, input_hash = file_hash(root / "matrix.json"), file_hash(root / "inputs.json")
    audit_hash = file_hash(Path(__file__))
    value = bound_json(root / "matrix.json", raw_hash)
    inputs = bound_json(root / "inputs.json", input_hash)
    if value.get("receiptHash") != digest({key: item for key, item in value.items() if key != "receiptHash"}):
        raise RuntimeError("cohort receipt hash does not bind its exact rows")
    if value.get("schemaVersion") != 2 or value.get("runtimeScope") != "approved-oci-render-with-pinned-host-decode-proof":
        raise RuntimeError("cohort runtime scope is unsupported")
    if value.get("passed") is not True or value.get("inputsRevalidated") is not True:
        raise RuntimeError("cohort is incomplete or failed")
    validate_completed(value)
    capabilities = _current(value, inputs)
    _rows(value, inputs, root, capabilities)
    _current(value, inputs)
    bound_json(root / "matrix.json", raw_hash)
    bound_json(root / "inputs.json", input_hash)
    if file_hash(Path(__file__)) != audit_hash:
        raise RuntimeError("OCI auditor changed during deep revalidation")
    return {"passed": True, "probes": len(value["probes"]), "rawReceiptHash": value["receiptHash"],
            "rawFileSha256": raw_hash, "inputsFileSha256": input_hash,
            "deepAudit": "media/archive/runtime/source/request bindings revalidated; original decode facts retained",
            "qualityClaim": value["qualityClaim"]}


def main() -> None:
    """Print a read-only audit result for one caller-selected private attempt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    print(json.dumps(audit(Path(parser.parse_args().directory)), sort_keys=True))


if __name__ == "__main__":
    main()
