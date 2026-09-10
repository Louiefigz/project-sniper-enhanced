#!/usr/bin/env python3
"""Translate a gated edit plan and sync it to a Palmier shadow timeline.
Usage: ``push.py PLAN MANIFEST [--name NAME] [--export final.palmier.mp4]``.
Every stdout line is NDJSON.  The top-level envelope guarantees exactly one
``{"error": ...}`` frame for any failed invocation, including manifest I/O,
graphics rendering, ffprobe, MCP transport, and argument failures.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audio.music_stage import resolve_music_track                 # noqa: E402
from fingerprints import plan_content_hash                        # noqa: E402
from graphics.graphics_render import (                           # noqa: E402
    render_entry_at_rate as render_entry,
)
from ingest_execution_authority import verify_execution_media_authority  # noqa: E402
from palmier.components import component_assets                   # noqa: E402
from palmier.export import FINAL_NAME                             # noqa: E402
from palmier.mcp_client import (PalmierClient, PalmierError,      # noqa: E402
                                PalmierWaiting, emit)
from palmier.master import (MasterFacts, approved_master,        # noqa: E402
                            authority_hash as _authority_hash)
from palmier.parity import analyze_parity                         # noqa: E402
from palmier.plan_input import read_plan                          # noqa: E402
from palmier.preflight import parity_block, preflight             # noqa: E402
from palmier.shadow import SyncRequest                            # noqa: E402
from palmier.sync import run_sync                                 # noqa: E402
from palmier.sync_lock import (SyncLock, SyncLockState,           # noqa: E402
                               SyncWaitReason)
from palmier.translate import TranslateRequest, translate         # noqa: E402
from template_usage_approval import require_current as require_template_usage_approval  # noqa: E402

@dataclass(frozen=True)
class CliArgs:
    """Parsed CLI options passed through the queue/reload loop."""

    plan_path: str
    manifest_path: str
    name: str | None
    export: str | None
    cache_dir: str | None
    dry_run: bool
    preflight: bool
    plan_stdin: bool
    require_source_set_admission: bool
    allow_legacy_unadmitted: bool

@dataclass(frozen=True)
class LoadedInputs:
    """Disk-plan identity plus its manifest-resolved execution view."""

    plan: dict
    manifest: dict
    source: dict
    plan_hash: str

def primary_source(manifest: dict) -> dict:
    """Return the complete primary source record or fail loudly."""
    sources = manifest.get("sources") or []
    primary = next((s for s in sources if s.get("role") == "primary"),
                   sources[0] if sources else None)
    if not primary:
        raise PalmierError("manifest has no sources")
    for key in ("path", "fps", "resolution"):
        if not primary.get(key):
            raise PalmierError(
                f"manifest source {primary.get('id')}: missing {key!r} — "
                "re-run ingest")
    return primary

def resolve_plan_assets(plan: dict, manifest_path: str) -> dict:
    """Resolve manifest-backed plan asset IDs without changing the disk plan."""
    music = plan.get("music") or {}
    if not music.get("enabled"):
        return plan
    path = resolve_music_track(music, None, manifest_path)
    return {**plan, "music": {**music, "path": path}}


def render_graphics(plan: dict, cache_dir: str | None,
                    fps: float = 30.0) -> dict[int, str]:
    """Render every selected component or fail the handoff as incomplete."""
    paths: dict[int, str] = {}
    for index, entry in enumerate(plan.get("graphicsTrack") or []):
        try:
            result = render_entry(entry, cache_dir, fps)
        except Exception as exc:
            raise PalmierError(
                f"required component graphicsTrack[{index}] could not be "
                f"rendered and proved: {exc}") from exc
        proof = result.get("proof")
        if not isinstance(proof, dict) or proof.get("schemaVersion") != 1:
            raise PalmierError(
                f"required component graphicsTrack[{index}] has no rendered "
                "asset proof")
        emit(status="graphic_rendered", index=index, kind=result["kind"],
             cached=result["cached"], path=result["path"],
             proofPath=proof.get("sidecar"))
        paths[index] = result["path"]
    return paths


def _json_file(path: str, label: str) -> dict:
    try:
        with open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} {path} is not a JSON object")
    return value


def _inputs(args: CliArgs) -> LoadedInputs:
    disk_plan = read_plan(args.plan_path, args.plan_stdin)
    manifest = _json_file(args.manifest_path, "asset manifest")
    verify_execution_media_authority(
        disk_plan, manifest, args.manifest_path)
    source = primary_source(manifest)
    plan = {
        **resolve_plan_assets(disk_plan, args.manifest_path),
        "_path": os.path.abspath(args.plan_path),
    }
    return LoadedInputs(plan, manifest, source, plan_content_hash(disk_plan))


def _project_name(args: CliArgs) -> str:
    if args.name:
        return args.name
    parent = os.path.basename(os.path.dirname(os.path.abspath(args.plan_path)))
    return parent or "sniper-push"


def _translate(args: CliArgs, plan: dict, master: MasterFacts,
               manifest: dict | None = None,
               preserve_components: bool = True) -> list[dict]:
    graphics = (render_graphics(plan, args.cache_dir, master.fps)
                if preserve_components else {})
    components = (component_assets(plan, manifest or {}, args.manifest_path,
                                   graphics) if preserve_components else {})
    request = TranslateRequest(
        fps=master.fps, source_path=master.path,
        graphics_paths=graphics, project_name=_project_name(args),
        width=master.width, height=master.height,
        export_path=args.export, master_path=master.path,
        master_hash=master.content_hash,
        master_duration_s=master.duration_s, master_fps=master.fps,
        component_paths=components)
    return translate(plan, request)


def _approved_master(args: CliArgs, loaded: LoadedInputs) -> MasterFacts:
    out_dir = os.path.dirname(os.path.abspath(args.plan_path))
    return approved_master(out_dir, args.plan_path, args.manifest_path,
                           loaded.plan_hash)


def _emit_dry_run(steps: list[dict]) -> None:
    for step in steps:
        summary = {k: v for k, v in step.items() if k != "rows"}
        if "rows" in step:
            summary["rows"] = len(step["rows"])
        emit(status="step", **summary)


def _validate_export(args: CliArgs, out_dir: str) -> None:
    if not args.export:
        return
    expected = os.path.join(out_dir, FINAL_NAME)
    if os.path.abspath(args.export) != expected:
        raise PalmierError(
            f"shadow sync publishes atomically to {expected}; --export must "
            "use that exact path")


def _sync_once(client: PalmierClient, args: CliArgs) -> str:
    loaded = _inputs(args)
    parity = analyze_parity(loaded.plan)
    if not parity["mirrorReady"]:
        emit(status="parity_blocked", parity=parity)
        raise PalmierError(parity_block(parity) or
                           "Palmier visual-mirror safety gate rejected the plan")
    out_dir = os.path.dirname(os.path.abspath(args.plan_path))
    _validate_export(args, out_dir)
    master = _approved_master(args, loaded)
    steps = _translate(args, loaded.plan, master, loaded.manifest)
    emit(status="translated", steps=len(steps), planHash=loaded.plan_hash,
         mirrorMode="visual-master", masterHash=master.content_hash)
    music_enabled = bool((loaded.plan.get("music") or {}).get("enabled"))
    request = SyncRequest(out_dir, master.content_hash, loaded.plan_hash, parity,
                          music_enabled=music_enabled,
                          authority_hash=master.content_hash,
                          master_path=master.path,
                          master_hash=master.content_hash,
                          master_duration_s=master.duration_s,
                          master_fps=master.fps,
                          master_width=master.width,
                          master_height=master.height,
                          master_end_frame=master.end_frame,
                          publish=bool(args.export),
                          timeline_label=(
                              f"Sniper · QC approved · {loaded.plan_hash[:8]}"))
    run_sync(client, steps, request)
    return loaded.plan_hash


def _lock_result(out_dir: str, plan_hash: str):
    result = SyncLock.acquire(out_dir, plan_hash)
    if result.state == SyncLockState.QUEUED:
        emit(status="queued", planHash=plan_hash, holderPid=result.holder_pid)
        return 75, None
    if result.state == SyncLockState.WAITING:
        reason = ("re-render active" if result.reason ==
                  SyncWaitReason.ASSEMBLE_ACTIVE else "another Palmier sync active")
        emit(status="waiting", reason=reason, holderPid=result.holder_pid)
        return 75, None
    return 0, result.lease


def _run_locked(args: CliArgs, initial_hash: str) -> int:
    out_dir = os.path.dirname(os.path.abspath(args.plan_path))
    code, lease = _lock_result(out_dir, initial_hash)
    if lease is None:
        return code
    client = PalmierClient()
    try:
        client.handshake()
        while True:
            try:
                completed_hash = _sync_once(client, args)
            except Exception:
                pending = lease.claim_pending()
                if pending:
                    emit(status="queue_retry", planHash=pending)
                    continue
                raise
            pending = lease.claim_pending()
            if not pending:
                emit(status="done", project=_project_name(args),
                     planHash=completed_hash)
                return 0
            emit(status="queue_draining", planHash=pending)
    finally:
        lease.release()


def _parse(argv: list[str] | None) -> CliArgs:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("plan_path")
    parser.add_argument("manifest_path")
    parser.add_argument("--name", default=None)
    parser.add_argument("--export", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument(
        "--require-source-set-admission", action="store_true",
        help="explicitly require source-set admission (the default)")
    policy.add_argument(
        "--allow-legacy-unadmitted", action="store_true",
        help="non-production migration only: accept a legacy manifest")
    parser.add_argument("--plan-stdin", action="store_true",
                        help="read an unsaved plan snapshot from stdin; preflight only")
    parsed = parser.parse_args(argv)
    return CliArgs(**vars(parsed))


def _run(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if not args.allow_legacy_unadmitted:
        os.environ["SNIPER_REQUIRE_SOURCE_SET_ADMISSION"] = "1"
    if args.plan_stdin and not args.preflight:
        raise PalmierError("--plan-stdin is allowed only with --preflight")
    if args.preflight:
        try:
            loaded = _inputs(args)
            if not args.plan_stdin:
                require_template_usage_approval(
                    args.plan_path, args.manifest_path,
                    os.path.dirname(os.path.abspath(args.plan_path)),
                    os.path.dirname(os.path.abspath(args.manifest_path)))
            master = _approved_master(args, loaded)
            request = TranslateRequest(
                fps=master.fps, source_path=master.path, graphics_paths={},
                project_name="preflight", width=master.width,
                height=master.height, master_path=master.path,
                master_hash=master.content_hash,
                master_duration_s=master.duration_s, master_fps=master.fps)
            verdict = preflight(loaded.plan, request)
        except Exception as exc:
            plan = loaded.plan if "loaded" in locals() else {}
            verdict = preflight(plan, None, str(exc))
        plan_hash = loaded.plan_hash if "loaded" in locals() else None
        emit(**verdict, planHash=plan_hash)
        return 0
    loaded = _inputs(args)
    require_template_usage_approval(
        args.plan_path, args.manifest_path,
        os.path.dirname(os.path.abspath(args.plan_path)),
        os.path.dirname(os.path.abspath(args.manifest_path)))
    if args.dry_run:
        steps = _translate(args, loaded.plan, _approved_master(args, loaded),
                           loaded.manifest, preserve_components=False)
        emit(status="translated", steps=len(steps),
             planHash=loaded.plan_hash)
        _emit_dry_run(steps)
        return 0
    out_dir = os.path.dirname(os.path.abspath(args.plan_path))
    return _run_locked(args, loaded.plan_hash)


def main(argv: list[str] | None = None) -> int:
    """Universal NDJSON error envelope; returns a process exit code."""
    try:
        return _run(argv)
    except PalmierWaiting as exc:
        emit(status="waiting", reason=str(exc))
        return 75
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        emit(error=f"push argument parsing exited {exc.code}")
        return int(exc.code) if isinstance(exc.code, int) else 1
    except BaseException as exc:
        emit(error=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
