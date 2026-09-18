"""TEST-only durable exact-name Docker intent; no result selection or new render.

Only the isolated TEST worker installs these local policy-module bindings.
The real launch, command restrictions and cleanup implementations are unchanged.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from color.deadline import require_time, wall_budget
from cut_preview_io import bound_json, digest, file_hash, read_bytes, write_new
from cross_runtime_canonical_json import canonical_compact_json
from headless import grade_observation_policy as policy
from headless.container_policy import required_runtime, reconcile_launch_abort, remove_container


def held_lifecycle(directory: Path, expected: str) -> dict:
    """Read only exact claim-bound TEST controls; never discover source receipts."""
    value = bound_json(directory / "TEST-lifecycle.json", expected)
    if value["kind"] != "TEST-grade-v2-lifecycle" or value["directory"] != str(directory) \
            or value["containerName"] != "sniper-grade-observation-" + directory.name.replace("-", ""):
        raise RuntimeError("Original TEST lifecycle does not match fixed attempt")
    for pin in value["pins"]:
        if file_hash(Path(pin["path"]), 128 * 1024 * 1024) != pin["sha256"]:
            raise RuntimeError("Original TEST launch/recovery implementation changed")
    bound_json(directory / "input.json", value["inputSha256"])
    return value


def runtime_record(runtime: object) -> dict:
    """Bind unchanged runtime controls including current socket identity."""
    info = os.stat(runtime.socket)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError("Owned Docker socket changed")
    approval = Path(policy.__file__).with_name("render_image_approval.json")
    return {"docker": runtime.docker, "dockerSha256": file_hash(Path(runtime.docker), 128 * 1024 * 1024),
            "socket": runtime.socket, "socketDevice": str(info.st_dev), "socketInode": str(info.st_ino),
            "imageId": runtime.image_id, "userId": runtime.user_id, "approvalSha256": file_hash(approval)}


def record_new(path: Path, value: dict) -> str:
    """Durably publish the intended exact bytes before any Docker launch call."""
    expected = (canonical_compact_json(value) + "\n").encode()
    write_new(path, value)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    os.chmod(path, 0o400)
    if read_bytes(path, 512 * 1024) != expected:
        raise RuntimeError("Intended launch publication bytes changed")
    return file_hash(path)


def install_launch_guard(directory: Path, expected: str) -> None:
    """Install one local name factory and one pre-call recorder, not global UUID state."""
    life = held_lifecycle(directory, expected)
    original_launch, original_command = policy._launch, policy._launch_command
    captured: dict = {}
    def name_once() -> uuid.UUID:
        """Allocate the pre-claimed name once; no second resource is supported."""
        if captured.get("allocated"):
            raise RuntimeError("TEST grade permits exactly one container")
        captured["allocated"] = True
        return uuid.UUID(directory.name)
    def command(runtime: object, context: tuple, request: dict) -> tuple[list[str], str]:
        """Retain the exact actual request used by the existing command builder."""
        attempt, name, source = context
        if Path(attempt) != directory / "execution" or name != life["containerName"] \
                or source != life["source"]["path"] or request["sourceSha256"] != life["source"]["sha256"]:
            raise RuntimeError("TEST launch differs from pre-claimed source/name")
        result = original_command(runtime, context, request)
        captured.update(request=json.loads(json.dumps(request)), command=list(result[0]))
        return result
    def launch(runtime: object, config: str, argv: list[str], name: str) -> str:
        """Persist exact intent before the unchanged owned Docker call can run."""
        held_lifecycle(directory, expected)
        if runtime_record(runtime) != life["runtime"] or argv != captured.get("command") \
                or name != life["containerName"] or Path(config) != directory / "execution":
            raise RuntimeError("TEST launch/runtime differs from original held controls")
        row = {"schemaVersion": 1, "kind": "TEST-grade-v2-launch-intent", "lifecycleSha256": expected,
               "inputSha256": life["inputSha256"], "name": name, "runtime": life["runtime"],
               "request": captured["request"], "command": argv, "commandHash": digest(argv)}
        intent_sha = record_new(directory / "TEST-launch-intent.json", row)
        result = original_launch(runtime, config, argv, name)
        record_new(directory / "TEST-launch-result.json", {"intentSha256": intent_sha, "containerId": result})
        return result
    policy.uuid = SimpleNamespace(uuid4=name_once)
    policy._launch_command, policy._launch = command, launch


def _absent(pid: int) -> None:
    """ESRCH only; this check supplements the independently observing TS owner."""
    try:
        os.kill(-pid, 0)
    except ProcessLookupError:
        return
    raise RuntimeError("Original owned group is present or absence is unknown")


def cleanup_exact(directory: Path, expected: str, deadline: float) -> dict:
    """Cleanup only the fixed held name, including a lost launch response."""
    life = held_lifecycle(directory, expected)
    _absent(life["supervisor"]["pid"])
    require_time(deadline)
    intent = directory / "TEST-launch-intent.json"
    try:
        raw = read_bytes(intent, 512 * 1024)
    except FileNotFoundError:
        raw = None
    runtime = required_runtime()
    if runtime_record(runtime) != life["runtime"]:
        raise RuntimeError("Original cleanup runtime changed")
    if raw is not None:
        _validate_intent(json.loads(raw), (directory, expected, life), runtime)
    require_time(deadline)
    # Pre-handshake crashes need not have created execution/. Use a fresh
    # private cleanup-only Docker config; never write retained observation files.
    control = tempfile.mkdtemp(prefix="TEST-cleanup-control-", dir=directory)
    # main() owns the one original timer across metadata, cleanup and stdout.
    # color.wall_budget intentionally rejects nested timers.
    reconcile_launch_abort(runtime, control, life["containerName"])
    removal = remove_container(runtime, control, life["containerName"])
    _absent(life["supervisor"]["pid"])
    held_lifecycle(directory, expected)
    if _optional_intent(intent) != raw or removal.get("canonicalAbsenceProved") is not True:
        raise RuntimeError("Exact launch cleanup changed or remains unknown")
    require_time(deadline)
    return {"state": "reconciled", "containerName": life["containerName"], "cleanupVerified": True,
            "intentSha256": file_hash(intent) if raw is not None else None, "removal": removal}


def _optional_intent(path: Path) -> bytes | None:
    """Absence is only a metadata observation, never proof of no launch."""
    try:
        return read_bytes(path, 512 * 1024)
    except FileNotFoundError:
        return None


def _validate_intent(value: dict, context: tuple, runtime: object) -> None:
    """An intact intent must match the exact fixed source/command/control record."""
    directory, expected, life = context
    request = policy._request(value["request"])
    command, _worker = policy._launch_command(runtime,
        (directory / "execution", life["containerName"], life["source"]["path"]), request)
    exact = {"schemaVersion": 1, "kind": "TEST-grade-v2-launch-intent", "lifecycleSha256": expected,
             "inputSha256": life["inputSha256"], "name": life["containerName"], "runtime": life["runtime"],
             "request": request, "command": command, "commandHash": digest(command)}
    if value != exact or request["sourceSha256"] != life["source"]["sha256"]:
        raise RuntimeError("Durable launch intent differs from exact original control")

def main() -> None:
    """Never accept caller commands or render during an explicit cleanup call."""
    if len(sys.argv) not in (3, 5):
        raise RuntimeError("Internal TEST worker requires exact lifecycle")
    started = time.monotonic()
    directory, expected = Path(sys.argv[1]), sys.argv[2]
    if len(sys.argv) == 5:
        if sys.argv[3] != "--cleanup" or not sys.argv[4].isdigit() or not 1 <= int(sys.argv[4]) <= 90000:
            raise RuntimeError("Invalid bounded cleanup-only request")
        deadline = started + int(sys.argv[4]) / 1000
        with wall_budget(deadline):
            result = cleanup_exact(directory, expected, deadline)
            print(json.dumps(result), flush=True)
        return
    from color import grade_project_worker
    from color.grade_observation_profile import V2_PROFILE
    value = held_lifecycle(directory, expected)
    install_launch_guard(directory, expected)
    sys.argv = [grade_project_worker.__file__, str(directory / "input.json"), value["inputSha256"], "--profile", V2_PROFILE]
    grade_project_worker.main()


if __name__ == "__main__":
    main()
