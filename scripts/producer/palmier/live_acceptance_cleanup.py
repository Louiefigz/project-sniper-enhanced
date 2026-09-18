"""Safe retained-cohort restoration and disposable-project cleanup."""
from __future__ import annotations

from typing import Any

from palmier.live_acceptance_session import (
    Evidence, restore_backup, restore_project, trash_disposable,
)
from palmier.live_acceptance_project_safety import (
    fingerprint_protected_project, require_same_protected_project,
    recover_disposable_project, require_surface,
)
from palmier.mcp_client import PalmierError


def _recover_project(client: Any, evidence: Evidence) -> dict | None:
    intent = evidence.value["phases"].get("projectIntent") or {}
    name = intent.get("name")
    if not isinstance(name, str):
        raise PalmierError("disposable project recovery has no exact name")
    return recover_disposable_project(client, name)


def _fallback_restore(
        client: Any, prior: dict, project: dict | None,
        errors: list[str]) -> None:
    try:
        if project and project.get("path"):
            client.call("close_project", {"path": project["path"]})
        previous = prior.get("project") or {}
        if previous.get("path"):
            client.call_json("open_project", {"path": previous["path"]})
            if prior.get("timelineId"):
                client.call("set_active_timeline", {
                    "timelineId": prior["timelineId"]})
    except Exception as exc:
        errors.append(f"project fallback restore: {exc}")


def _restore_local(evidence: Evidence, errors: list[str]) -> None:
    backups = evidence.value.get("resume") or evidence.value
    for key in ("pointerBackup", "sidecarBackup"):
        try:
            restore_backup(backups[key])
            evidence.value["cleanup"][key] = "restored"
        except Exception as exc:
            errors.append(f"{key}: {exc}")


def _verify_protected(
        client: Any, evidence: Evidence,
        prior: dict | None, errors: list[str]) -> None:
    path = (evidence.value.get("config") or {}).get(
        "protected_project_path")
    before = evidence.value["phases"].get("protectedBefore")
    if not isinstance(path, str):
        return
    try:
        if not isinstance(prior, dict) or not isinstance(before, dict):
            raise PalmierError(
                "protected-project cleanup authority is unavailable")
        after = fingerprint_protected_project(
            client, path, prior["surface"])
        require_same_protected_project(before, after)
        evidence.value["cleanup"]["protectedProject"] = after
    except Exception as exc:
        errors.append(f"protected project: {exc}")


def cleanup_cohort(
        client: Any | None, evidence: Evidence,
        prior: dict | None, project: dict | None) -> list[str]:
    """Restore user-visible state and trash only an approved successful cohort."""
    errors: list[str] = []
    if client is not None and project is None:
        try:
            project = _recover_project(client, evidence)
        except Exception as exc:
            errors.append(f"project recovery: {exc}")
    if client is not None and prior is not None:
        try:
            evidence.value["cleanup"]["restore"] = restore_project(
                client, prior, project)
        except Exception as exc:
            errors.append(f"project restore: {exc}")
            _fallback_restore(client, prior, project, errors)
    if client is not None:
        _verify_protected(client, evidence, prior, errors)
    _restore_local(evidence, errors)
    trash = ((evidence.value.get("cleanupPolicy") or {})
             .get("trashDisposable") is True)
    if client is not None and project is not None and trash and not errors:
        try:
            active = next((row for row in client.call_json(
                "get_projects", {}).get("projects") or []
                if isinstance(row, dict) and row.get("isActive")), None)
            if isinstance(active, dict) and active.get("id") == project.get("id"):
                raise PalmierError("disposable project is still active")
            evidence.value["cleanup"]["trashed"] = trash_disposable(
                project, str(project.get("name")))
        except Exception as exc:
            errors.append(f"project trash: {exc}")
    elif project is not None:
        evidence.value["cleanup"]["retainedForReview"] = project.get("path")
    if client is not None and prior is not None:
        try:
            evidence.value["cleanup"]["finalOpenState"] = require_surface(
                client, prior["surface"])
        except Exception as exc:
            errors.append(f"final open state: {exc}")
    evidence.value["cleanup"]["errors"] = errors
    evidence.save()
    return errors
