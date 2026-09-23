"""Shared supervision for bounded ordinary preview and capability inspections.

These jobs return technical JSON evidence, never native export or delivery
approval. Media decoders/renderers retain their existing nested local jails.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cut_preview_io import bound_json, write_new
from graphics.graphics_render import HYPERFRAMES_BIN
from studio.native_export import active_owner_snapshot
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import REPO, digest
from studio.native_stage_evidence import STABLE_FIELDS, _owned_completion, require

STATUS = "ordinary-preview-inspection-complete"
SANDBOX = Path(__file__).with_name("native_localhost_only.sb")


def implementation_pins(tools: dict) -> dict[str, str]:
    """Bind producer execution, the pinned component SDK and resolved tools."""
    producer = REPO / "scripts/producer"
    files = [file for file in producer.rglob("*.py") if "tests" not in file.parts]
    files += [file for file in Path(HYPERFRAMES_BIN).parent.rglob("*") if file.is_file()]
    files += [Path(value).resolve(strict=True) for value in tools.values()]
    files += [Path(sys.executable).resolve(strict=True), SANDBOX,
              REPO / "templates/motion/package-lock.json"]
    return {str(file): digest(file) for file in sorted(set(files))}


def run_inspection(worker: Path, root: Path, request: dict) -> dict:
    """Admit one worker, retain its completion and release owned resources."""
    tools, environment = local_environment()
    root.mkdir(mode=0o700)
    request = {**request, "tools": tools, "pins": {**implementation_pins(tools), str(worker): digest(worker)}}
    file = root / "request.json"
    write_new(file, request)
    environment.update(SNIPER_NODE_PATH=tools["node"], SNIPER_INSPECTION_REQUEST=str(file),
                       SNIPER_INSPECTION_OWNER=str(root / "inspection.render.json"),
                       SNIPER_INSPECTION_PID=str(os.getpid()))
    cli = Path(HYPERFRAMES_BIN)
    settings = NativeRunConfig(Path(request["project"]), root, cli,
        [sys.executable, "-B", str(worker), "--worker", str(file)], environment,
        {"output": str(root / "result.json"), "sdkSha256": digest(cli), "sandboxSha256": digest(SANDBOX)},
        deadline=4200, idle_deadline=600, capacity_wait_seconds=600, success_status=STATUS,
        additional_pins={**request["pins"], str(file): digest(file)})
    owner = NativeRun("inspection", settings)
    if not owner.execute():
        raise RuntimeError(f"Ordinary preview failed; retained {root / 'inspection.render.log'}")
    result = {"path": str(root / "result.json"), "sha256": digest(root / "result.json"),
              "owner": str(owner.path), "ownerSha256": digest(owner.path)}
    read_inspection(result)
    return result


def require_worker(file: Path, worker: Path) -> dict:
    """Reject direct, changed or detached workers before any media operation."""
    require(os.environ.get("SNIPER_INSPECTION_REQUEST") == str(file), "Inspection requires its live owner")
    owner_file = file.parent / "inspection.render.json"
    require(os.environ.get("SNIPER_INSPECTION_OWNER") == str(owner_file), "Inspection owner changed")
    request, owner = bound_json(file), active_owner_snapshot(owner_file)
    pid = int(os.environ.get("SNIPER_INSPECTION_PID", "0"))
    require(pid > 1, "Inspection supervisor missing")
    os.kill(pid, 0)
    require(owner.get("project") == request["project"] and owner.get("output") == str(file.parent / "result.json")
            and owner.get("args") == [sys.executable, "-B", str(worker), "--worker", str(file)]
            and owner.get("status") in {"running", "preparing", "waiting-for-capacity"}
            and not owner.get("completedAt") and not owner.get("abortReason")
            and owner["additionalFilePinsBefore"].get(str(file)) == digest(file), "Inspection live binding changed")
    for filename, sha in request["pins"].items():
        require(owner["additionalFilePinsBefore"].get(filename) == sha
                and digest(Path(filename)) == sha, "Inspection implementation changed")
    return request


def read_inspection(reference: dict) -> dict:
    """Read original completed owner evidence without transferring old approval."""
    file, owner_file = Path(reference["path"]), Path(reference["owner"])
    require(owner_file == file.parent / "inspection.render.json", "Inspection result escaped its owner")
    owner = bound_json(owner_file, reference["ownerSha256"])
    _owned_completion(owner, STATUS)
    require(all(owner.get(key) is True for key in STABLE_FIELDS)
            and owner.get("cleanup", {}).get("verified") is True
            and owner["cleanup"].get("survivors") == []
            and owner.get("output") == str(file)
            and owner.get("additionalFilePinsBefore") == owner.get("additionalFilePinsAfter"),
            "Inspection did not finish with unchanged inputs and verified cleanup")
    request_file = file.parent / "request.json"
    require(owner["additionalFilePinsBefore"].get(str(request_file)) == digest(request_file),
            "Inspection request changed after completion")
    return bound_json(file, reference["sha256"])
