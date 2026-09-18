#!/usr/bin/env python3
"""Create a non-authoritative Palmier working view from stable saved media.

The draft is intentionally separate from the verified visual-mirror proof. It
lets Palmier be the viewer while Sniper plans/renders/QCs in the background;
the approved push later creates a fresh timeline and replaces this sidecar
with the normal verified-mirror record.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fingerprints import file_sha256                              # noqa: E402
from ingest_execution_authority import execution_media_authority_entries  # noqa: E402
from ingest_probe import probe_media                              # noqa: E402
from palmier.executor import Executor                             # noqa: E402
from palmier.mcp_client import (PalmierClient, PalmierError,      # noqa: E402
                                PalmierWaiting, emit)
from palmier.media import MediaLibrary                            # noqa: E402
from palmier.mirror import sidecar_ownership                      # noqa: E402
from palmier.shadow import ShadowSession, SyncRequest             # noqa: E402
from palmier.sync import load_sidecar, sidecar_path               # noqa: E402
from palmier.sync_lock import (SyncLock, SyncLockState,           # noqa: E402
                               SyncWaitReason)
from palmier.timeline_authority import record_active_authority   # noqa: E402
from palmier.timeline_guard import reconcile_working_authority   # noqa: E402


@dataclass(frozen=True)
class DraftInput:
    """Stable source and Palmier project facts for a working view."""

    source_path: str
    source_hash: str
    duration_s: float
    fps: float
    width: int
    height: int
    asset_kind: str = "source"


@dataclass(frozen=True)
class DraftContext:
    """CLI paths and operator choices for one managed working view."""

    out_dir: str
    manifest_path: str
    name: str
    mode: str
    working_path: str | None = None


def _json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read asset manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("asset manifest is not an object")
    return value


def _working_path(ctx: DraftContext) -> str | None:
    if ctx.working_path is None:
        return None
    path = os.path.abspath(ctx.working_path)
    allowed = {
        os.path.join(ctx.out_dir, "base_final.mp4"),
        os.path.join(ctx.out_dir, "final.mp4"),
    }
    if path not in allowed or os.path.realpath(path) != path \
            or os.path.islink(path) or not os.path.isfile(path):
        raise PalmierError(
            "Palmier working media must be this project's governed base or final")
    return path


def _draft_input(ctx: DraftContext) -> DraftInput:
    manifest = _json(ctx.manifest_path)
    execution_media_authority_entries({}, manifest, ctx.manifest_path)
    source = _manifest_source(manifest)
    working_path = _working_path(ctx)
    source_path = os.path.abspath(working_path or source["path"])
    asset_kind = "saved-cut" if working_path else "source"
    try:
        probe = probe_media(source_path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PalmierError(f"cannot probe Palmier draft source: {exc}") from exc
    facts = (probe.duration, probe.fps, probe.width, probe.height)
    if any(value is None for value in facts) or probe.vfr:
        raise PalmierError("Palmier draft requires CFR source video facts")
    width, height = _canvas(ctx.mode, int(probe.width), int(probe.height))
    content_hash = source.get("contentHash") if not working_path else None
    if not isinstance(content_hash, str) or len(content_hash) != 64:
        content_hash = file_sha256(source_path)
    return DraftInput(source_path, content_hash, float(probe.duration),
                      float(probe.fps), width, height, asset_kind)


def _manifest_source(manifest: dict) -> dict:
    sources = manifest.get("sources") or []
    source = next((row for row in sources if row.get("role") == "primary"),
                  sources[0] if sources else None)
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise PalmierError("asset manifest has no primary source path")
    return source


def _canvas(mode: str, width: int, height: int) -> tuple[int, int]:
    if mode == "short":
        return 1080, 1920
    if mode != "longform":
        raise PalmierError("Palmier draft mode must be short or longform")
    return width, height


def _request(out_dir: str, draft: DraftInput) -> SyncRequest:
    return SyncRequest(
        out_dir, draft.source_hash, f"draft-{draft.source_hash}",
        {"schemaVersion": 1, "mirrorReady": False,
         "workspaceMode": "managed-draft"})


def _lanes(name: str, draft: DraftInput) -> dict:
    return {"project": {"name": name, "fps": round(draft.fps),
                         "width": draft.width, "height": draft.height}}


def _persist(out_dir: str, session: ShadowSession, bindings,
             draft: DraftInput) -> dict:
    if session.target is None or session.build_id is None:
        raise PalmierError("Palmier draft identity disappeared")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = {
        "schemaVersion": 4, "ownership": "sniper",
        "workspaceMode": "managed-draft", "mirrorMode": None,
        "projectId": session.target.project_id,
        "projectName": session.target.name, "projectPath": session.target.path,
        "projectSettings": {"fps": round(draft.fps),
                            "width": draft.width, "height": draft.height},
        "mediaMap": bindings.media_map, "latestTimelineId": session.build_id,
        "timelineIds": [{"id": session.build_id,
                         "name": session.build_name,
                         "status": "working-view", "createdAt": now}],
        "draft": {"assetKind": draft.asset_kind, "sourcePath": draft.source_path,
                  "sourceHash": draft.source_hash, "createdAt": now,
                  "authoritative": False},
    }
    target = sidecar_path(out_dir)
    temp = f"{target}.{os.getpid()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return state


def _activate_existing(client: PalmierClient, out_dir: str,
                       draft: DraftInput, name: str) -> bool:
    state = load_sidecar(out_dir)
    if not state:
        return False
    if sidecar_ownership(state) == "palmier":
        raise PalmierError("Palmier owns this project; Sniper cannot replace its view")
    if state.get("workspaceMode") != "managed-draft":
        emit(status="workspace_exists", workspaceMode="verified-mirror")
        return True
    saved = state.get("draft") or {}
    if saved.get("sourceHash") != draft.source_hash:
        return False
    session = ShadowSession(client, _request(out_dir, draft),
                            _lanes(name, draft), state)
    session.ensure_project()
    authority, change = reconcile_working_authority(client, out_dir, state)
    if change != "unchanged" or authority.get("origin") != "sniper-bootstrap":
        emit(status="draft_ready", timelineId=authority.get("timelineId"),
             reused=True, authoritative=True, source="palmier-manual")
        return True
    session.activate_generated(state.get("latestTimelineId"), require_human=False)
    emit(status="draft_ready", timelineId=state.get("latestTimelineId"),
         reused=True, authoritative=False)
    return True


def create_draft(
    client: PalmierClient,
    ctx: DraftContext,
    draft: DraftInput | None = None,
) -> None:
    """Create or activate one stable-media managed working timeline."""
    draft = draft or _draft_input(ctx)
    if _activate_existing(client, ctx.out_dir, draft, ctx.name):
        return
    state = load_sidecar(ctx.out_dir)
    session = ShadowSession(client, _request(ctx.out_dir, draft),
                            _lanes(ctx.name, draft), state)
    session.ensure_project()
    library = MediaLibrary(client, draft.source_hash, session.assert_project)
    bindings = library.ensure({"src": draft.source_path},
                              (state or {}).get("mediaMap", {}))
    complete = False
    try:
        session.create_shadow()
        editor = Executor(client, session.assert_build)
        editor.project_fps = round(draft.fps)
        editor.media, editor.media_s = bindings.refs, bindings.seconds
        editor.run({"op": "cuts", "entries": [{
            "mediaKey": "src", "source": [0.0, draft.duration_s],
            "startFrame": 0,
            "endFrame": round(draft.duration_s * editor.project_fps),
            "speed": 1.0}]})
        session.restore_human(strict=True)
        session.finalize([])
        session.build_name = f"Sniper working view · {draft.asset_kind}"
        client.call("organize_media", {"renames": [{
            "item": session.build_id, "name": session.build_name}]})
        session.activate_generated()
        if session.target is None:
            raise PalmierError("Palmier draft project identity disappeared")
        record_active_authority(client, ctx.out_dir,
                                session.target.project_id,
                                "sniper-bootstrap")
        _persist(ctx.out_dir, session, bindings, draft)
        complete = True
        emit(status="draft_ready", timelineId=session.build_id,
             reused=False, authoritative=False)
    finally:
        if not complete:
            session.restore_human(strict=False)
            session.mark_failed()


def _run_locked(args) -> int:
    ctx = DraftContext(args.out_dir, args.manifest_path, args.name, args.mode,
                       args.working_path)
    draft = _draft_input(ctx)
    result = SyncLock.acquire(
        args.out_dir, f"draft-{draft.source_hash}", queue_if_busy=False)
    if result.state != SyncLockState.ACQUIRED or result.lease is None:
        reason = "render active" if result.reason == SyncWaitReason.ASSEMBLE_ACTIVE \
            else "another Palmier operation is active"
        emit(status="waiting", reason=reason, holderPid=result.holder_pid)
        return 75
    try:
        client = PalmierClient()
        client.handshake()
        create_draft(client, ctx, draft)
        return 0
    finally:
        result.lease.release()


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("manifest_path")
    parser.add_argument("out_dir")
    parser.add_argument("--name", required=True)
    parser.add_argument("--mode", choices=("short", "longform"), required=True)
    parser.add_argument("--working-media")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument(
        "--require-source-set-admission", action="store_true",
        help="explicitly require source-set admission (the default)")
    policy.add_argument(
        "--allow-legacy-unadmitted", action="store_true",
        help="non-production migration only: accept a legacy manifest")
    args = parser.parse_args(argv)
    if not args.allow_legacy_unadmitted:
        os.environ["SNIPER_REQUIRE_SOURCE_SET_ADMISSION"] = "1"
    os.makedirs(args.out_dir, exist_ok=True)
    args.working_path = args.working_media
    return _run_locked(args)


def main() -> None:
    try:
        raise SystemExit(_run())
    except PalmierWaiting as exc:
        emit(status="waiting", reason=str(exc))
        raise SystemExit(75) from exc
    except (OSError, ValueError, PalmierError) as exc:
        emit(error=str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
