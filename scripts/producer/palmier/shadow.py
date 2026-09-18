#!/usr/bin/env python3
"""Guarded Palmier project selection and shadow-timeline lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from palmier.mcp_client import (PalmierClient, PalmierError, PalmierWaiting,
                                emit)


@dataclass(frozen=True)
class SyncRequest:
    """Immutable inputs for one shadow-timeline transaction."""

    out_dir: str
    source_hash: str
    plan_hash: str
    parity: dict
    keep_timelines: int = 3
    music_enabled: bool = False
    authority_hash: str | None = None
    master_path: str | None = None
    master_hash: str | None = None
    master_duration_s: float | None = None
    master_fps: float | None = None
    master_width: int | None = None
    master_height: int | None = None
    master_end_frame: int | None = None
    publish: bool = False
    timeline_label: str | None = None


@dataclass(frozen=True)
class ProjectTarget:
    """Stable target project identity learned from Palmier."""

    project_id: str
    name: str
    path: str


def _active_project(info: dict) -> dict | None:
    active = next((p for p in info.get("projects", []) if p.get("isActive")),
                  None)
    if active:
        return active
    summary = info.get("active") or {}
    return summary if summary.get("path") else None


def prior_timelines(sidecar: dict) -> list[dict]:
    """Sidecar-owned timeline records, ignoring legacy/raw-id shapes."""
    records = sidecar.get("timelineIds") or []
    return [row for row in records if isinstance(row, dict) and row.get("id")]


class ShadowSession:
    """One guarded shadow build within a stable Palmier project."""

    def __init__(self, client: PalmierClient, request: SyncRequest,
                 lanes: dict, sidecar: dict | None):
        self.client = client
        self.request = request
        self.lanes = lanes
        self.sidecar = sidecar or {}
        self.target: ProjectTarget | None = None
        self.human_timeline_id: str | None = None
        self.build_id: str | None = None
        self.build_name: str | None = None

    def ensure_project(self) -> None:
        """Select the target without stealing focus from another project."""
        info = self.client.call_json("get_projects", {})
        target = self._resolve_target(info)
        active = _active_project(info)
        if target and not self._same_project(active, target):
            if active:
                raise PalmierWaiting(
                    f"another Palmier project is active ({active.get('name')}); "
                    f"open {target.get('name')} and sync again")
            self.client.call_json("open_project", {"path": target["path"]})
        elif target is None:
            if active:
                raise PalmierWaiting(
                    f"another Palmier project is active ({active.get('name')}); "
                    f"create/open {self.lanes['project']['name']} and sync again")
            self._create_project()
            info = self.client.call_json("get_projects", {})
            target = self._resolve_target(info)
        self._capture_target(target)
        self._verify_project_settings()

    def _resolve_target(self, info: dict) -> dict | None:
        projects = info.get("projects", [])
        project_id = self.sidecar.get("projectId")
        if project_id:
            found = next((p for p in projects if p.get("id") == project_id), None)
            if found:
                return found
        path = self.sidecar.get("projectPath")
        if path:
            found = next((p for p in projects if p.get("path") == path), None)
            if found:
                return found
        name = self.sidecar.get("projectName") or self.lanes["project"]["name"]
        matches = [p for p in projects if p.get("name") == name]
        if len(matches) == 1:
            return matches[0]
        active = next((p for p in matches if p.get("isActive")), None)
        if active:
            return active
        if len(matches) > 1:
            raise PalmierError(f"multiple Palmier projects named {name!r}; "
                               "open the intended one before syncing")
        return None

    @staticmethod
    def _same_project(active: dict | None, target: dict) -> bool:
        if not active:
            return False
        return ((active.get("id") and active.get("id") == target.get("id"))
                or active.get("path") == target.get("path"))

    def _create_project(self) -> None:
        project = self.lanes["project"]
        self.client.call_json("new_project", {"name": project["name"],
                                                "fps": project["fps"]})
        self.client.call("set_project_settings", {
            "width": project["width"], "height": project["height"]})
        emit(status="project_created", name=project["name"],
             fps=project["fps"], width=project["width"],
             height=project["height"])

    def _capture_target(self, target: dict | None) -> None:
        if not target or not target.get("id") or not target.get("path"):
            raise PalmierError("could not resolve the target Palmier project")
        self.target = ProjectTarget(target["id"], target["name"], target["path"])
        live = self.client.call_json("get_timeline", {})
        if not live.get("id"):
            raise PalmierError("target project has no active timeline")
        self.human_timeline_id = live["id"]
        emit(status="project_ready", name=self.target.name,
             humanTimeline=self.human_timeline_id)

    def _verify_project_settings(self) -> None:
        live = self.client.call_json("get_timeline", {})
        project = self.lanes["project"]
        actual = (live.get("fps"), live.get("width"), live.get("height"))
        expected = (project["fps"], project["width"], project["height"])
        if actual != expected:
            raise PalmierError(
                f"target Palmier project settings {actual} do not match "
                f"the plan {expected}; change settings explicitly in Palmier")

    def assert_project(self, phase: str) -> None:
        info = self.client.call_json("get_projects", {})
        target = self.target.__dict__ if self.target else {}
        if not self.target or not self._same_project(_active_project(info), target):
            raise PalmierError(
                f"IDENTITY CHANGED before {phase}: target Palmier project is "
                "no longer active; aborting without reopening it")

    def assert_build(self, phase: str) -> None:
        self.assert_project(phase)
        active_id = self.client.call_json("get_timeline", {}).get("id")
        if not self.build_id or active_id != self.build_id:
            raise PalmierError(
                f"IDENTITY CHANGED before {phase}: active timeline "
                f"{active_id!r} is not shadow {self.build_id!r}")

    def assert_human(self, phase: str) -> None:
        self.assert_project(phase)
        active_id = self.client.call_json("get_timeline", {}).get("id")
        if active_id != self.human_timeline_id:
            raise PalmierError(
                f"IDENTITY CHANGED before {phase}: active timeline "
                f"{active_id!r} is not restored human timeline "
                f"{self.human_timeline_id!r}")

    def activate_generated(self, timeline_id: str | None = None,
                           require_human: bool = True) -> str:
        """Activate one proven generated timeline without crossing projects."""
        target_id = timeline_id or self.build_id
        if not target_id:
            raise PalmierError("cannot activate generated timeline: id is missing")
        if require_human:
            self.assert_human("generated timeline activation")
        else:
            self.assert_project("generated timeline activation")
        media = self.client.call_json("get_media", {})
        timeline_ids = {row.get("timelineId")
                        for row in media.get("timelines", [])}
        if target_id not in timeline_ids:
            raise PalmierError(
                f"cannot activate generated timeline {target_id!r}: not in target project")
        self.build_id = target_id
        self.client.call("set_active_timeline", {"timelineId": target_id})
        self.assert_project("generated timeline activation verification")
        active_id = self.client.call_json("get_timeline", {}).get("id")
        if active_id != target_id:
            raise PalmierError(
                f"generated timeline activation returned {active_id!r}, "
                f"expected {target_id!r}")
        emit(status="generated_timeline_active", timelineId=target_id)
        return target_id

    def create_shadow(self) -> None:
        self.assert_project("create shadow timeline")
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        self.build_name = f"sniper-building-{self.request.plan_hash[:8]}-{stamp}"
        result = self.client.call_json("create_timeline", {"name": self.build_name})
        live = self.client.call_json("get_timeline", {})
        self.build_id = result.get("timelineId") or result.get("id") or live.get("id")
        has_clips = any(t.get("clips") for t in live.get("tracks", []))
        if live.get("id") != self.build_id or live.get("totalFrames") or has_clips:
            raise PalmierError("created shadow timeline is not active and empty")
        emit(status="shadow_created", timelineId=self.build_id,
             name=self.build_name)

    def restore_human(self, strict: bool) -> None:
        if not self.target or not self.human_timeline_id:
            return
        info = self.client.call_json("get_projects", {})
        if not self._same_project(_active_project(info), self.target.__dict__):
            if strict:
                raise PalmierError("cannot restore timeline: human changed project")
            emit(status="restore_skipped", reason="human changed project")
            return
        active_id = self.client.call_json("get_timeline", {}).get("id")
        if active_id == self.human_timeline_id:
            return
        if active_id != self.build_id:
            if strict:
                raise PalmierError("cannot restore timeline: human changed timeline")
            emit(status="restore_skipped", reason="human changed timeline")
            return
        self.client.call("set_active_timeline", {
            "timelineId": self.human_timeline_id})
        self.assert_human("timeline restore verification")
        emit(status="timeline_restored", timelineId=self.human_timeline_id)

    def mark_failed(self) -> None:
        if not self.build_id or not self.build_name:
            return
        try:
            self.assert_human("failed shadow rename")
            failed = f"{self.build_name}-FAILED"
            self.client.call("organize_media", {"renames": [{
                "item": self.build_id, "name": failed}]})
            self.build_name = failed
            emit(status="shadow_failed", timelineId=self.build_id, name=failed)
        except PalmierError as exc:
            emit(status="warning", warning=f"failed shadow cleanup skipped: {exc}")

    def finalize(self, prior: list[dict]) -> tuple[str, list[dict]]:
        self.assert_human("shadow finalization")
        name = self.request.timeline_label or f"sniper-v{self.request.plan_hash[:8]}"
        self.client.call("organize_media", {"renames": [{
            "item": self.build_id, "name": name}]})
        self.build_name = name
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        current = {"id": self.build_id, "name": name,
                   "planHash": self.request.plan_hash,
                   "status": "ready", "createdAt": now}
        records = [current] + [r for r in prior if r.get("id") != self.build_id]
        self._archive(records[self.request.keep_timelines:])
        return name, records

    def _archive(self, records: list[dict]) -> None:
        ids = [r.get("id") for r in records if r.get("id")]
        if not ids:
            return
        self.assert_human("shadow history archive")
        media = self.client.call_json("get_media", {})
        live_ids = {t.get("timelineId") for t in media.get("timelines", [])}
        owned = [timeline_id for timeline_id in ids if timeline_id in live_ids]
        if owned:
            self.client.call("organize_media", {"moves": [{
                "items": owned, "into": "_sniper/history"}]})
            emit(status="shadow_archived", count=len(owned))
