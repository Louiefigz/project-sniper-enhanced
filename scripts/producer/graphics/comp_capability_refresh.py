"""Sequential genuine capability recomputation with owned OCI resources.

This is 53 default/probe-spec30fps measurements, not a released-rate matrix or
per-input visual approval. Never rehash old rows. Every attempt is retained;
publication requires a complete current valid inventory and exact cleanup.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from color.deadline import wall_budget
from cut_preview_io import file_hash, read_bytes, write_new
from graphics.comp_capability_artifact import (
    MOTION_DIR, build_artifact, capability_row_issue, composition_paths, current_source_digest, load_artifact,
)
from graphics.comp_catalog_probe import _measure_artifact, probe_duration, probe_spec, static_probe
from graphics.graphics_render import render_entry_for_capability_probe
from graphics.template_contract import declared_variables
from graphics.render_tools import resolve_tools
from graphics.comp_capability_resume import resume_rows
from graphics.comp_capability_timing import phase_timings
from graphics.comp_capability_budget import boundary, COHORT_SECONDS
from graphics.comp_capability_lint import preflight_root_lint, lint_validator_state
from headless.render_runtime import RendererRuntime, current_render_build_manifest
from headless.resource_ledger import ResourceRequest, container_lease, registered_containers, removed_containers

PROBE_SECONDS = 90


def runtime() -> RendererRuntime:
    """Require existing approved local controls and exact host proof decoders."""
    root = str(Path(__file__).resolve().parents[3])
    tools = [os.path.realpath(os.environ[f"SNIPER_PROOF_{name}_PATH"]) for name in ("FFMPEG", "FFPROBE")]
    return RendererRuntime(root, root, os.path.realpath(sys.executable),
        os.path.realpath(os.environ["SNIPER_DOCKER_PATH"]), os.path.realpath(os.environ["SNIPER_DOCKER_SOCKET"]),
        os.environ["SNIPER_RENDER_IMAGE_ID"], os.environ["SNIPER_RENDER_UID_GID"], *tools,
        timeout_seconds=PROBE_SECONDS)


@contextmanager
def owned_environment(name: str) -> Iterator[None]:
    """Sequential only: preserve every unrelated environment value."""
    previous = os.environ.get("SNIPER_RENDER_CONTAINER_NAME")
    os.environ["SNIPER_RENDER_CONTAINER_NAME"] = name
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SNIPER_RENDER_CONTAINER_NAME", None)
        else:
            os.environ["SNIPER_RENDER_CONTAINER_NAME"] = previous


def source_state() -> dict:
    """Hold both render closure and actual measurement/runner implementations."""
    producer = Path(__file__).resolve().parents[1]
    extra = (Path(__file__), producer / "graphics/comp_catalog_probe.py",
             producer / "color/deadline.py", producer / "planner/graphics_anchors.py",
             producer / "graphics/comp_capability_resume.py", producer / "graphics/comp_capability_timing.py",
             producer / "graphics/comp_capability_budget.py")
    return {"motionSourceDigest": current_source_digest(),
        "rootLintValidator": lint_validator_state(),
        "renderBuild": current_render_build_manifest(runtime()),
        "measurementSources": {str(path.relative_to(producer)): file_hash(path) for path in extra}}


def _render_json(rendered: dict) -> dict:
    """Project the known archive-member tuple exactly as its persisted proof."""
    proof = rendered["proof"]
    runtime_proof = proof["runtimeAttestation"]
    archive = runtime_proof["retainedInputArchive"]
    projected = {**proof, "runtimeAttestation": {**runtime_proof,
        "retainedInputArchive": {**archive, "members": list(archive["members"])}}}
    persisted = json.loads(read_bytes(Path(proof["sidecar"])))
    if {key: item for key, item in projected.items() if key != "sidecar"} != persisted:
        raise RuntimeError("returned capability proof differs from exact persisted proof")
    return {**rendered, "proof": projected}


def _preflight(root: Path) -> None:
    """Fail before media work unless all measurement pins execute as expected."""
    rows = {}
    for name, path in resolve_tools().items():
        if name in {"ffmpeg", "ffprobe"} and os.path.realpath(shutil.which(name) or "") != path:
            raise RuntimeError("measurement PATH differs from its exact executable pin")
        argument = "--version" if name in {"node", "browser"} else "-version"
        result = subprocess.run([path, argument], capture_output=True, text=True,
                                timeout=10, check=True)
        rows[name] = {"path": path, "sha256": file_hash(Path(path)),
                      "version": result.stdout.splitlines()[0]}
    write_new(root / "measurement-tool-preflight.json", rows)


def _entry(kind: str, source: str) -> dict:
    """Use the existing composition-specific duration, inputs, and anchor."""
    spec = probe_spec(kind, declared_variables(source))
    return {"kind": kind, "spec": spec, "anchor": "free-band", "outStart": 0,
            "outEnd": probe_duration(kind, spec)}


def _probe(directory: Path, entry: dict, state: dict) -> dict:
    """Normal capability render/proof, then actual terminal and bbox measurement."""
    control = runtime()
    resources = ResourceRequest(str(directory), directory.name, control.docker,
        control.docker_socket, control.image_id, control.user_id)
    cache = directory / "cache"
    cache.mkdir(mode=0o700)
    with container_lease(resources) as name:
        write_new(directory / "request.json", {"entry": entry, "fps": "30", "containerName": name,
            "imageId": control.image_id, "sourceState": state, "scope": "capability-measurement-not-delivery"})
        with owned_environment(name), wall_budget(time.monotonic() + PROBE_SECONDS):
            rendered = render_entry_for_capability_probe(entry, str(cache), "30")
        proof = rendered["proof"]
        observed = proof.get("runtimeAttestation") or {}
        if rendered.get("cached") is not False or rendered.get("fps") != "30" \
                or observed.get("imageId") != control.image_id \
                or observed.get("containerRemoval", {}).get("canonicalAbsenceProved") is not True:
            raise RuntimeError("capability probe lacks fresh exact OCI execution/cleanup")
        if observed.get("containerAfterOutput", {}).get("Name") != f"/{name}":
            raise RuntimeError("capability probe belongs to another owned container")
        held_media = file_hash(Path(rendered["path"]))
        measured = {"probeDurationS": entry["outEnd"]}
        with wall_budget(time.monotonic() + 30):
            _measure_artifact(measured, rendered["path"], proof["asset"]["frameCount"], proof.get("terminalFrame"))
        if file_hash(Path(rendered["path"])) != held_media or proof["asset"]["sha256"] != held_media:
            raise RuntimeError("capability media changed during measurement")
        write_new(directory / "actual-render-result.json", _render_json(rendered))
    if registered_containers(resources) or removed_containers(resources) != (name,):
        raise RuntimeError("capability exact container absence is unproved")
    return {"measurements": measured, "mediaSha256": held_media, "containerName": name,
            "cleanupVerified": True, "mediaPath": rendered["path"]}


def _record(directory: Path, entry: dict, state: dict) -> dict:
    """Retain every genuine probe result, including failed attempts and timing."""
    started = time.monotonic()
    row = {"kind": entry["kind"], "passed": False, "phaseTimings": []}
    try:
        with phase_timings(row["phaseTimings"]):
            row.update(_probe(directory, entry, state))
        row["passed"] = True
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        row["error"] = f"{type(error).__name__}: {error}"[:4000]
    row["elapsedMs"] = round((time.monotonic() - started) * 1000)
    write_new(directory / "result.json", row)
    print(json.dumps(row), flush=True)
    return row


def _write_artifact(path: Path, artifact: dict) -> None:
    """Preserve the existing artifact's Python-JSON float/digest contract."""
    data = (json.dumps(artifact, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + "\n").encode("ascii")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(root: Path, artifact: dict, previous: bytes) -> None:
    """Generated current artifact only after genuine measurements; preserve exact old bytes."""
    target = Path(MOTION_DIR) / "comp_capabilities.json"
    if read_bytes(target) != previous:
        raise RuntimeError("current capability artifact changed before publication")
    if artifact["sourceDigest"] != current_source_digest():
        raise RuntimeError("motion sources changed before capability publication")
    temporary = target.with_name(f".comp-capabilities-{root.name}.pending.json")
    _write_artifact(temporary, artifact)
    os.replace(temporary, target)


def execute(root: Path, value: dict, started: float, publish: bool) -> None:
    """Lint before native tools, then run the original guarded capability cohort."""
    if value.get("stopRequested"):
        raise RuntimeError("capability cohort stopped before static root lint")
    lint = preflight_root_lint(root, started + value.get("cohortLimitSeconds", COHORT_SECONDS))
    _preflight(root)
    initial = source_state()
    if initial["motionSourceDigest"] != lint["sourceState"]["motionSourceDigest"] \
            or initial["rootLintValidator"] != lint["sourceState"]["validator"]:
        raise RuntimeError("original static root-lint source/validator changed before capability work")
    boundary(root, value, started, len(lint["sourceState"]["entries"]))
    write_new(root / "source-before.json", initial)
    old = read_bytes(Path(MOTION_DIR) / "comp_capabilities.json")
    backup = root / "previous-comp_capabilities.json"
    with backup.open("xb") as handle:
        handle.write(old)
        handle.flush()
        os.fsync(handle.fileno())
    sources = {Path(path).stem: Path(path).read_text() for path in composition_paths()}
    entries = {kind: (_entry(kind, source), source) for kind, source in sources.items()}
    if value.get("cohortLimitSeconds") == 2700:
        value["plannedProbeSeconds"] = {kind: entry[0]["outEnd"] for kind, entry in entries.items()}
    comps = {}
    if value.get("resumeDirectory"):
        with wall_budget(min(time.monotonic() + 90, started + value["cohortLimitSeconds"])):
            comps, rows = resume_rows((value["resumeDirectory"], str(root)), initial, entries)
        value["probes"].extend(rows)
        value["revalidatedRows"] = len(rows)
    for kind, source in sources.items():
        if kind in comps:
            continue
        boundary(root, value, started, len(sources))
        if source_state() != initial:
            raise RuntimeError("capability source/runtime closure changed during cohort")
        directory = root / kind
        directory.mkdir(mode=0o700)
        row = _record(directory, _entry(kind, source), initial)
        value["probes"].append(row)
        if not row["passed"]:
            raise RuntimeError(f"capability probe failed for {kind}; no catalog publication")
        comps[kind] = {**static_probe(kind, source), **row["measurements"]}
        if capability_row_issue(comps[kind]) is not None:
            raise RuntimeError(f"measured capability row is invalid for {kind}")
    _finish(root, value, (started, publish), (initial, sources, comps, old))


def _finish(root: Path, value: dict, controls: tuple, evidence: tuple) -> None:
    """Require complete current readback before generated publication."""
    started, publish = controls
    initial, sources, comps, old = evidence
    boundary(root, value, started, len(sources))
    if source_state() != initial or len(comps) != len(sources):
        raise RuntimeError("capability completion source/inventory mismatch")
    write_new(root / "source-after.json", source_state())
    artifact = build_artifact(comps)
    _write_artifact(root / "comp_capabilities.json", artifact)
    loaded, issue = load_artifact(str(root / "comp_capabilities.json"))
    if issue or set(loaded or {}) != set(sources):
        raise RuntimeError(f"fresh capability readback failed: {issue}")
    if source_state() != initial or any(capability_row_issue(row) for row in loaded.values()):
        raise RuntimeError("capability current source/row revalidation failed before publication")
    if publish:
        _publish(root, artifact, old)
    value.update(passed=True, published=publish, artifactSha256=file_hash(root / "comp_capabilities.json"))


def main() -> None:
    """Retain the caller's original cohort elapsed time and all failure facts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--elapsed-before-seconds", type=float, default=0)
    parser.add_argument("--total-budget-seconds", type=int, choices=(1500, 2100, 2700), default=1500)
    parser.add_argument("--resume")
    args = parser.parse_args()
    if not 0 <= args.elapsed_before_seconds < args.total_budget_seconds:
        parser.error("elapsed-before-seconds must retain a positive cohort budget")
    root = Path(args.out).resolve()
    root.mkdir(mode=0o700, exist_ok=False)
    attempt_started = time.monotonic()
    started = attempt_started - args.elapsed_before_seconds
    value = {"passed": False, "published": False, "probes": [], "artifactDir": str(root),
             "cohortLimitSeconds": args.total_budget_seconds, "resumeDirectory": args.resume,
             "rateMatrixQualified": False, "deliveryApproved": False,
             "limits": {"concurrentRenders": 1, "cpusPerRender": 4, "memoryGiBPerRender": 4,
                        "renderWorkSeconds": PROBE_SECONDS, "measurementWorkSeconds": 30}}
    previous = signal.signal(signal.SIGINT, lambda _sig, _frame: value.update(stopRequested=True))
    print(json.dumps({"phase": "start", "artifactDir": str(root)}), flush=True)
    try:
        execute(root, value, started, args.publish)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        value["error"] = f"{type(error).__name__}: {error}"[:4000]
    finally:
        signal.signal(signal.SIGINT, previous)
    value["elapsedMs"] = round((time.monotonic() - attempt_started) * 1000)
    value["cohortElapsedMs"] = round((time.monotonic() - started) * 1000)
    value["elapsedBeforeAttemptMs"] = round(args.elapsed_before_seconds * 1000)
    try:
        boundary(root, value, started, len(composition_paths()))
    except RuntimeError as error:
        value["budgetStop"] = str(error)
    write_new(root / "cohort.json", value)
    print(json.dumps({key: item for key, item in value.items() if key != "probes"}), flush=True)
    raise SystemExit(0 if value["passed"] else 1)


if __name__ == "__main__":
    main()
