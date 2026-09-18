"""Durable attempt-owned Docker resource registration and reconciliation."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from typing import Iterator

from .container_policy import (
    DockerRuntime,
    reconcile_launch_abort,
    remove_container,
)
from .durable_files import (
    locked_private_dir,
    read_private_file,
    write_pending_replace,
)

LEDGER_NAME = "resource-ledger.json"
_LOCK_NAME = ".resource-ledger.lock"
_PENDING_NAME = ".resource-ledger.pending"
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CONTAINER = re.compile(r"sniper-render-[0-9a-f]{32}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_STATES = {"REGISTERED", "REMOVED"}
_MAX_RESOURCES = 4096


class ResourceLedgerError(RuntimeError):
    """A resource record is unsafe, corrupt, or cannot be reconciled."""


@dataclass(frozen=True)
class ResourceRequest:
    """Trusted control inputs for one attempt's Docker resources."""

    attempt_root: str
    attempt_id: str
    docker: str
    docker_socket: str
    image_id: str
    user_id: str


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("ascii")


def _validate_request(request: ResourceRequest) -> None:
    paths = (request.attempt_root, request.docker, request.docker_socket)
    if any(not os.path.isabs(path) or os.path.realpath(path) != path for path in paths):
        raise ResourceLedgerError("resource control paths must be canonical absolute paths")
    if (not _ATTEMPT.fullmatch(request.attempt_id)
            or not _IMAGE.fullmatch(request.image_id)):
        raise ResourceLedgerError("resource attempt or image identity is invalid")


def _control_digest(request: ResourceRequest) -> str:
    value = {"docker": request.docker, "dockerSocket": request.docker_socket,
             "imageId": request.image_id, "userId": request.user_id}
    return hashlib.sha256(b"sniper-resource-control-v1\0" + _canonical(value)).hexdigest()


def _empty(request: ResourceRequest) -> dict:
    return {"attemptId": request.attempt_id, "resources": [], "schemaVersion": 1}


def _validate_ledger(value: object, request: ResourceRequest) -> dict:
    valid = (isinstance(value, dict)
             and set(value) == {"attemptId", "resources", "schemaVersion"}
             and value.get("schemaVersion") == 1
             and value.get("attemptId") == request.attempt_id
             and isinstance(value.get("resources"), list)
             and len(value["resources"]) <= _MAX_RESOURCES)
    if not valid:
        raise ResourceLedgerError("resource ledger has an invalid envelope")
    names = set()
    for row in value["resources"]:
        row_ok = (isinstance(row, dict)
                  and set(row) == {"containerName", "controlDigest", "state"}
                  and _CONTAINER.fullmatch(str(row.get("containerName", "")))
                  and re.fullmatch(r"[0-9a-f]{64}", str(row.get("controlDigest", "")))
                  and row.get("state") in _STATES)
        if not row_ok or row["containerName"] in names:
            raise ResourceLedgerError("resource ledger has an invalid container record")
        names.add(row["containerName"])
    return value


def _read_locked(dir_fd: int, request: ResourceRequest) -> dict:
    try:
        os.stat(LEDGER_NAME, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _empty(request)
    raw = read_private_file(dir_fd, LEDGER_NAME)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourceLedgerError("resource ledger is invalid JSON") from exc
    value = _validate_ledger(value, request)
    if raw != _canonical(value):
        raise ResourceLedgerError("resource ledger is not exact canonical JSON")
    return value


def _write_locked(dir_fd: int, value: dict) -> None:
    write_pending_replace(
        dir_fd, (_PENDING_NAME, LEDGER_NAME), _canonical(value))


def _register(request: ResourceRequest) -> str:
    name = f"sniper-render-{uuid.uuid4().hex}"
    with locked_private_dir(request.attempt_root, _LOCK_NAME) as dir_fd:
        value = _read_locked(dir_fd, request)
        if len(value["resources"]) >= _MAX_RESOURCES:
            raise ResourceLedgerError("resource ledger is full")
        value["resources"].append({
            "containerName": name, "controlDigest": _control_digest(request),
            "state": "REGISTERED"})
        _write_locked(dir_fd, value)
    return name


def _mark_removed(request: ResourceRequest, name: str) -> None:
    with locked_private_dir(request.attempt_root, _LOCK_NAME) as dir_fd:
        value = _read_locked(dir_fd, request)
        matches = [row for row in value["resources"]
                   if row["containerName"] == name]
        if len(matches) != 1 or matches[0]["controlDigest"] != _control_digest(request):
            raise ResourceLedgerError("resource removal does not match its registration")
        matches[0]["state"] = "REMOVED"
        _write_locked(dir_fd, value)


def _runtime(request: ResourceRequest) -> DockerRuntime:
    return DockerRuntime(request.docker, request.docker_socket,
                         request.image_id, request.user_id, {})


def _cleanup(request: ResourceRequest, name: str, aborted: bool) -> dict:
    with tempfile.TemporaryDirectory(
            prefix=".resource-reconcile-", dir=request.attempt_root) as stage:
        config = os.path.join(stage, "docker-config")
        os.mkdir(config, 0o700)
        if aborted:
            reconcile_launch_abort(_runtime(request), config, name)
            return {"containerRef": name, "canonicalAbsenceProved": True,
                    "method": "late-create-reconciliation"}
        return remove_container(_runtime(request), config, name)


@contextlib.contextmanager
def container_lease(request: ResourceRequest) -> Iterator[str]:
    """Register before spawn; prove absence before marking the lease removed."""
    _validate_request(request)
    name = _register(request)
    aborted = True
    try:
        yield name
        aborted = False
    finally:
        _cleanup(request, name, aborted)
        _mark_removed(request, name)


def registered_containers(request: ResourceRequest) -> tuple[str, ...]:
    """Return exact active names, rejecting records for another control plane."""
    _validate_request(request)
    with locked_private_dir(request.attempt_root, _LOCK_NAME) as dir_fd:
        value = _read_locked(dir_fd, request)
    expected = _control_digest(request)
    active = [row for row in value["resources"] if row["state"] == "REGISTERED"]
    if any(row["controlDigest"] != expected for row in active):
        raise ResourceLedgerError("active resource uses another Docker control plane")
    return tuple(row["containerName"] for row in active)


def removed_containers(request: ResourceRequest) -> tuple[str, ...]:
    """Return prior absence-proved names for cache-runtime attestation."""
    _validate_request(request)
    with locked_private_dir(request.attempt_root, _LOCK_NAME) as dir_fd:
        value = _read_locked(dir_fd, request)
    expected = _control_digest(request)
    removed = [row for row in value["resources"] if row["state"] == "REMOVED"]
    if any(row["controlDigest"] != expected for row in removed):
        raise ResourceLedgerError("removed resource uses another Docker control plane")
    return tuple(row["containerName"] for row in removed)


def reconcile_registered_containers(request: ResourceRequest) -> tuple[dict, ...]:
    """Startup hook: remove every durably registered exact container name."""
    receipts = []
    for name in registered_containers(request):
        receipts.append(_cleanup(request, name, True))
        _mark_removed(request, name)
    return tuple(receipts)
