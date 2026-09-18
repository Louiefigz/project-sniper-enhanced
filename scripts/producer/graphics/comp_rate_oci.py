"""Opt-in sequential real OCI catalog/rate qualification; no retained-v1 rewrite.

Run from producer PYTHONPATH with configured approved Docker runtime and exact
SNIPER_PROOF_FFMPEG_PATH / SNIPER_PROOF_FFPROBE_PATH. Creates a NEW attempt only.
Four-frame probes establish codec/canvas/exact-rate decode, not visual quality.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cut_preview_io import digest, file_hash, write_new
from graphics.comp_rate_artifact import PROBE_FRAMES, RELEASED_RATES, _stream_issue
from graphics.comp_rate_matrix import _full_decode, _probe_stream
from graphics.comp_rate_oci_inputs import prepare_inputs, qualified_catalog, snapshot_for, source_epoch
from headless.container_policy import attest_image, required_runtime
from headless.container_renderer import RenderRequest, render_to

COHORT_BUDGET_S = 1800


def cohort_boundary(started: float, total: int, value: dict) -> None:
    """Stop only between owned probes, retaining mandatory container cleanup."""
    elapsed = time.monotonic() - started
    rows = value["probes"]
    measured = sum(row["elapsedMs"] for row in rows) / 1000
    projected = elapsed + measured / len(rows) * (total - len(rows)) if rows else elapsed
    value["cohortBudget"] = {"softBudgetSeconds": COHORT_BUDGET_S,
                              "elapsedSeconds": round(elapsed, 3), "projectedSeconds": round(projected, 3),
                              "enforcement": "between-probe; active probe and mandatory cleanup are not force-killed"}
    if value.get("stopRequested"):
        raise RuntimeError("operator requested a stop; last owned probe and cleanup completed")
    if elapsed >= COHORT_BUDGET_S or (len(rows) >= 10 and projected > COHORT_BUDGET_S):
        raise RuntimeError("cohort soft budget or measured completion projection exceeded; inspect partial evidence")


def proof_tools() -> tuple[dict[str, str], dict]:
    """Use explicit host proof decoders; never mislabel them OCI render tools."""
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        raw = os.environ.get(f"SNIPER_PROOF_{name.upper()}_PATH", "")
        if not os.path.isabs(raw):
            raise RuntimeError("exact proof decoder pins are required")
        path = str(Path(raw).resolve(strict=True))
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise RuntimeError("proof decoder is not an executable")
        tools[name] = path
    receipts = {name: {"path": path, "sha256": file_hash(Path(path), 512 * 1024 * 1024)}
                for name, path in sorted(tools.items())}
    return tools, receipts


def _probe(row: dict, tools: dict[str, str], canvas: list[int]) -> dict:
    """Render one exact sealed request and retain full decode/runtime evidence."""
    started = time.monotonic()
    output = Path(row["directory"]) / "probe.mov"
    request = RenderRequest(row["composition"], "mov", str(output), snapshot_for(row),
                            f"sniper-render-{uuid.uuid4().hex}", row["rate"])
    runtime = render_to(request)
    stream = _probe_stream(str(output), row["rate"], tools)
    issue = _stream_issue(stream, row["rate"], canvas)
    if issue:
        raise RuntimeError(issue)
    _full_decode(str(output), tools)
    return {"kind": row["kind"], "rate": row["rate"], "duration": row["duration"],
            "passed": True, "decoded": True, "stream": stream,
            "mediaSha256": file_hash(output), "inputSha256": row["inputSha256"],
            "runtimeReceiptSha256": file_hash(Path(str(output) + ".runtime.json")),
            "containerRemoval": runtime["containerRemoval"],
            "elapsedMs": round((time.monotonic() - started) * 1000)}


def _record_probe(row: dict, tools: dict[str, str], canvas: list[int]) -> dict:
    """Retain an honest failing row; abort further work if cleanup is unproved."""
    started = time.monotonic()
    try:
        result = _probe(row, tools, canvas)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        result = {"kind": row["kind"], "rate": row["rate"], "passed": False,
                  "error": str(exc), "elapsedMs": round((time.monotonic() - started) * 1000)}
    write_new(Path(row["directory"]) / "result.json", result)
    print(json.dumps({key: result.get(key) for key in ("kind", "rate", "passed", "elapsedMs", "error")}), flush=True)
    return result


def validate_completed(value: dict) -> None:
    """Require the full current cross product and positively measured probe rows."""
    expected = {(kind, rate) for kind in value["inputs"]["compositionKinds"] for rate in RELEASED_RATES}
    rows = value["probes"]
    if len(rows) != len(expected) or {(row["kind"], row["rate"]) for row in rows} != expected:
        raise RuntimeError("OCI rate cross-product is incomplete or repeats identities")
    if any(row.get("passed") is not True or row.get("decoded") is not True
           or row.get("containerRemoval", {}).get("canonicalAbsenceProved") is not True for row in rows):
        raise RuntimeError("OCI rate matrix contains failed or cleanup-unverified probes")


def run(directory: Path) -> dict:
    """Execute only new four-frame probes; never reuse or relabel old media rows."""
    started = time.monotonic()
    directory.mkdir(mode=0o700, exist_ok=False)
    value = {"schemaVersion": 2, "kind": "hyperframes-oci-released-rate-matrix",
             "runtimeScope": "approved-oci-render-with-pinned-host-decode-proof",
             "passed": False, "startedAt": datetime.now(timezone.utc).isoformat(), "probes": [],
             "limits": {"concurrentRenders": 1, "cpusPerRender": 4, "memoryGiBPerRender": 4,
                        "probeFrames": PROBE_FRAMES, "perRenderDeadlineS": 600},
             "qualityClaim": "Four-frame exact-rate/codec/alpha-format/canvas/full-decode only; not motion or perceptual quality."}
    value["runnerStartup"] = {"sha256": file_hash(Path(__file__).resolve()), "capturedBeforeExecution": True}
    prior_handler = signal.signal(signal.SIGINT, lambda _signal, _frame: value.update(stopRequested=True))
    try:
        _execute(directory, value, started)
        validate_completed(value)
        if file_hash(Path(__file__).resolve()) != value["runnerStartup"]["sha256"]:
            raise RuntimeError("runner source changed during execution")
        value["passed"] = True
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        value["error"] = str(exc)
    finally:
        signal.signal(signal.SIGINT, prior_handler)
    value["elapsedMs"] = round((time.monotonic() - started) * 1000)
    value["receiptHash"] = digest(value)
    write_new(directory / "matrix.json", value)
    print(json.dumps({"out": str(directory / "matrix.json"), "passed": value["passed"],
                      "probes": len(value["probes"]), "elapsedMs": value["elapsedMs"],
                      "error": value.get("error")}), flush=True)
    return value


def _execute(directory: Path, value: dict, started: float) -> None:
    """Freeze sources before rendering and verify scoped identities afterward."""
    runtime = required_runtime()
    with tempfile.TemporaryDirectory(prefix="rate-image-attestation-") as control:
        image = attest_image(runtime, control)
    tools, receipts = proof_tools()
    value["imageId"], value["renderToolClosure"] = image["Id"], runtime.approval["probedClosure"]
    value["proofTools"] = receipts
    header, requests, paths = prepare_inputs(directory)
    value["inputs"] = header
    capabilities, _ = qualified_catalog()
    write_new(directory / "cohort-context.json", {key: item for key, item in value.items() if key != "probes"})
    print(json.dumps({"prepared": len(requests), "inputBytes": header["inputBytes"],
                      "sourceDigest": header["sourceDigest"]}), flush=True)
    for request in requests:
        cohort_boundary(started, len(requests), value)
        result = _record_probe(request, tools, capabilities[request["kind"]]["canvas"])
        value["probes"].append(result)
        if not result["passed"]:
            raise RuntimeError("A real OCI rate probe failed; retained evidence requires inspection before further launches")
    cohort_boundary(started, len(requests), value)
    if source_epoch(paths) != header["sourceEpoch"] or proof_tools()[1] != receipts:
        raise RuntimeError("source/runtime policy or proof decoder changed during OCI matrix")
    with tempfile.TemporaryDirectory(prefix="rate-image-reattest-") as control:
        if attest_image(required_runtime(), control)["Id"] != image["Id"]:
            raise RuntimeError("approved render image changed during OCI matrix")
    value["inputsRevalidated"] = True


def main() -> None:
    """Require a caller-selected new evidence directory, never a retained file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    directory = Path(args.out_dir).absolute()
    value = run(directory)
    raise SystemExit(0 if value["passed"] else 1)


if __name__ == "__main__":
    main()
