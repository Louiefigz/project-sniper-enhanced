"""Exact claimed-resource reconciliation shared by opening and body owners.

The caller must separately prove its process groups stopped and authenticate
the request/intent. No source decode, render, directory discovery or widened
cleanup allowance is introduced here. Legacy error wording remains unchanged.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash, real_directory
from headless.container_policy import DockerRuntime, remove_container
from headless.resource_ledger import (ResourceRequest, reconcile_registered_containers,
                                      registered_containers, removed_containers)


def _absent(path: Path) -> bool:
    """Do not mistake a dangling alias or special file for a nonexistent record."""
    return not os.path.lexists(path)


def _unarmed(attempt: Path) -> bool:
    """No ledger-like state may be hidden by a missing before-registration marker."""
    leaves = ("resource-ledger.json", ".resource-ledger.pending", ".resource-ledger.lock", "execution-request.json")
    if any(not _absent(attempt / name) for name in leaves):
        raise RuntimeError("opening cleanup found resource state without its armed registration intent")
    return True


def _absence(request: ResourceRequest, names: tuple[str, ...]) -> list[dict]:
    """Observe exact same-daemon absence even for a previously REMOVED ledger row."""
    runtime = DockerRuntime(request.docker, request.docker_socket, request.image_id, request.user_id, {})
    with tempfile.TemporaryDirectory(prefix=".opening-cleanup-", dir=request.attempt_root) as temporary:
        config = Path(temporary) / "docker-config"
        config.mkdir(mode=0o700)
        return [remove_container(runtime, str(config), name) for name in names]


def reconcile_claimed_resource(request: ResourceRequest, expected_intent: dict, order: int) -> dict:
    """Reconcile only one externally authenticated candidate-order resource intent."""
    attempt = Path(request.attempt_root)
    if _absent(attempt):
        parent = attempt.parent
        while _absent(parent):
            parent = parent.parent
        real_directory(parent)
        return {"order": order, "state": "not-initialized", "containerNames": [], "cleanupVerified": True}
    real_directory(attempt)
    info = attempt.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("opening cleanup attempt is not private and owned")
    marker = attempt / "registration-intent.json"
    if _absent(marker) and _unarmed(attempt):
        return {"order": order, "state": "initialized-unarmed", "containerNames": [], "cleanupVerified": True}
    if digest(bound_json(marker)) != digest(expected_intent):
        raise RuntimeError("opening cleanup armed marker differs from exact claim/control/order")
    ledger = attempt / "resource-ledger.json"
    if _absent(ledger):
        raise RuntimeError("opening cleanup UNKNOWN: armed registration has no durable ledger")
    file_hash(ledger)
    before = registered_containers(request) + removed_containers(request)
    if len(before) != 1:
        raise RuntimeError("opening cleanup UNKNOWN: exactly one registration is required per claimed graphic")
    recovered = reconcile_registered_containers(request)
    remaining, removed = registered_containers(request), removed_containers(request)
    if remaining or set(removed) != set(before):
        raise RuntimeError("opening cleanup did not settle every exact registered resource")
    observations = _absence(request, removed)
    if any(item.get("canonicalAbsenceProved") is not True for item in observations):
        raise RuntimeError("opening cleanup UNKNOWN: same-daemon absence was not proved")
    return {"order": order, "state": "reconciled-absence", "containerNames": list(removed),
        "reconciliation": list(recovered), "absence": observations, "cleanupVerified": True}
