"""Measure the current compatibility catalog with owned native resource limits.

This is a bounded inspection job, not a Short/Long export or an editorial
approval. Each worker uses the existing pinned component renderer, including
its localhost-only sandbox, asset proof and alpha/bounding-box measurements.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, read_bytes, real_directory, write_new
from graphics.comp_capability_artifact import (
    MOTION_DIR, build_artifact, capability_row_issue, composition_paths,
    current_source_digest, load_artifact,
)
from graphics.comp_capability_lint import preflight_root_lint
from graphics.comp_capability_refresh import _publish, _write_artifact
from graphics.comp_catalog_probe import (
    _measure_artifact, probe_duration, probe_spec, static_probe,
)
from graphics.graphics_render import HYPERFRAMES_BIN, render_entry_for_capability_probe
from graphics.template_contract import declared_variables
from graphics.visual_source_policy import require_integrated
from studio.native_export import active_owner_snapshot
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import digest
from studio.native_stage_evidence import require
from studio.owned_inspection import implementation_pins

STATUS = "native-capability-measured"
WORK_SECONDS = 180
HERE = Path(__file__).resolve()
SANDBOX = HERE.parents[1] / "studio/native_localhost_only.sb"


def entry_for(kind: str) -> dict:
    """Use the production probe's exact defaults and completion duration."""
    require_integrated(kind)
    source = (Path(MOTION_DIR) / "compositions" / f"{kind}.html").read_text()
    spec = probe_spec(kind, declared_variables(source))
    duration = probe_duration(kind, spec)
    require(0 < duration <= 30, "Capability inspection exceeds the 30-second bound")
    return {"kind": kind, "spec": spec, "anchor": "free-band",
            "outStart": 0, "outEnd": duration}


def require_worker(file: Path) -> dict:
    """A direct worker cannot bypass the live shared supervisor or its pins."""
    require(str(file) == os.environ.get("SNIPER_CAPABILITY_REQUEST"),
            "Capability worker requires the shared native owner")
    request = bound_json(file)
    root = file.parent
    require(file.name == "request.json" and root.resolve() == root
            and request["scope"] == "catalog-capability-inspection-v1"
            and request["project"] == MOTION_DIR, "Invalid capability request")
    owner_file = root / "native.render.json"
    require(str(owner_file) == os.environ.get("SNIPER_CAPABILITY_OWNER"),
            "Capability owner path changed")
    owner = active_owner_snapshot(owner_file)
    pid = int(os.environ.get("SNIPER_CAPABILITY_PID", "0"))
    require(pid > 1, "Capability supervisor is missing")
    os.kill(pid, 0)
    require(owner["project"] == MOTION_DIR and owner["output"] == str(root / "result.json")
            and owner["args"] == [sys.executable, "-B", str(HERE), "--worker", str(file)]
            and owner["status"] in {"preparing", "waiting-for-capacity", "running"}
            and not owner.get("abortReason") and not owner.get("completedAt")
            and owner["additionalFilePinsBefore"].get(str(file)) == digest(file),
            "Capability owner does not bind this exact live worker")
    require(request["entry"] == entry_for(request["entry"]["kind"]),
            "Capability worker input differs from current defaults")
    require(current_source_digest() == request["sourceDigest"], "Capability sources changed")
    for filename, sha in request["pins"].items():
        require(digest(Path(filename)) == sha, "Capability implementation changed")
    return request


def worker(file: Path) -> None:
    """Perform real rendering/proof/measurement; never fabricate an old row."""
    request = require_worker(file)
    root, entry = file.parent, request["entry"]
    cache = root / "cache"
    cache.mkdir(mode=0o700)
    rendered = render_entry_for_capability_probe(entry, str(cache), "30")
    require(rendered["cached"] is False and rendered["fps"] == "30",
            "Capability measurement must use a fresh 30fps render")
    proof = rendered["proof"]
    media = Path(rendered["path"])
    require(digest(media) == proof["asset"]["sha256"], "Capability render bytes changed")
    measurements = {"probeDurationS": entry["outEnd"]}
    _measure_artifact(measurements, str(media), proof["asset"]["frameCount"],
                      proof.get("terminalFrame"))
    require_worker(file)
    require(digest(media) == proof["asset"]["sha256"], "Capability bytes changed during measurement")
    write_new(root / "result.json", {
        "kind": entry["kind"], "measurements": measurements,
        "render": rendered, "scope": request["scope"],
    })


def measure(root: Path, kind: str, context: tuple[dict, dict, dict]) -> dict:
    """Release and verify each owned renderer before admitting the next one."""
    tools, environment, pins = context
    root.mkdir(mode=0o700)
    request = {"scope": "catalog-capability-inspection-v1", "project": MOTION_DIR,
               "entry": entry_for(kind), "sourceDigest": current_source_digest(), "pins": pins}
    file = root / "request.json"
    write_new(file, request)
    child_environment = {**environment, "SNIPER_NODE_PATH": tools["node"],
        "SNIPER_CAPABILITY_REQUEST": str(file),
        "SNIPER_CAPABILITY_OWNER": str(root / "native.render.json"),
        "SNIPER_CAPABILITY_PID": str(os.getpid())}
    cli = Path(HYPERFRAMES_BIN)
    settings = NativeRunConfig(
        Path(MOTION_DIR), root, cli,
        [sys.executable, "-B", str(HERE), "--worker", str(file)], child_environment,
        {"output": str(root / "result.json"), "sdkSha256": digest(cli),
         "sandboxSha256": digest(SANDBOX)}, sandbox=SANDBOX,
        deadline=WORK_SECONDS + 600, idle_deadline=WORK_SECONDS,
        capacity_wait_seconds=600, success_status=STATUS,
        additional_pins={**pins, str(file): digest(file)})
    owner = NativeRun("native", settings)
    if not owner.execute():
        raise RuntimeError(f"Capability {kind} failed; retained log: {root / 'native.render.log'}")
    result = bound_json(root / "result.json")
    require(result["kind"] == kind and request["sourceDigest"] == current_source_digest(),
            "Capability result/source binding changed")
    result["owner"] = {"path": str(owner.path), "sha256": digest(owner.path)}
    return result


def qualify(root: Path, publish: bool) -> dict:
    """Publish only a complete, current catalog after genuine native measurements."""
    root = root.absolute()
    real_directory(root.parent)
    root.mkdir(mode=0o700)
    tools, environment = local_environment()
    os.environ["SNIPER_NODE_PATH"] = tools["node"]
    preflight_root_lint(root, time.monotonic() + 60)
    source_digest = current_source_digest()
    previous = read_bytes(Path(MOTION_DIR) / "comp_capabilities.json")
    (root / "previous-comp_capabilities.json").write_bytes(previous)
    pins = implementation_pins(tools)
    write_new(root / "source-before.json", {"sourceDigest": source_digest, "pins": pins})
    rows, evidence = {}, []
    for file in composition_paths():
        require(current_source_digest() == source_digest, "Catalog changed during qualification")
        path = Path(file)
        measured = measure(root / path.stem, path.stem, (tools, environment, pins))
        rows[path.stem] = {**static_probe(path.stem, path.read_text()), **measured["measurements"]}
        require(capability_row_issue(rows[path.stem]) is None, "Incomplete capability measurement")
        evidence.append(measured)
    require(current_source_digest() == source_digest, "Catalog changed before publication")
    artifact = build_artifact(rows)
    _write_artifact(root / "comp_capabilities.json", artifact)
    loaded, issue = load_artifact(str(root / "comp_capabilities.json"))
    require(not issue and set(loaded or {}) == set(rows), f"Capability readback failed: {issue}")
    if publish:
        _publish(root, artifact, previous)
    result = {"passed": True, "published": publish, "rows": evidence,
              "sourceDigest": source_digest, "artifactSha256": digest(root / "comp_capabilities.json"),
              "rateMatrixQualified": False, "deliveryApproved": False,
              "scope": "Seven compatibility ports at default/probe inputs and 30fps; not the full upstream catalog"}
    write_new(root / "cohort.json", result)
    return result


def main() -> None:
    """Separate the supervised worker from the maintainer's cohort command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if not args.out:
        parser.error("--out is required")
    result = qualify(args.out, args.publish)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}))


if __name__ == "__main__":
    main()
