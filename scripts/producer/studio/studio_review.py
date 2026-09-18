#!/usr/bin/env python3
"""studio_review — operator CLI for the HyperFrames Studio review lane.

CLI::

    studio_review.py open    <producer_dir> [--force]
    studio_review.py stop    <producer_dir>
    studio_review.py status  <producer_dir>
    studio_review.py context <producer_dir> [--context-fields selection,lint]
    studio_review.py sync    <producer_dir> [--apply] [--assemble]
                             [--manifest M]
    studio_review.py propose-text <package.json> --help

The manual-control loop after a render: ``open`` generates/refreshes
``<producer_dir>/studio/`` from ``edit_plan.json`` + ``base_final.mp4`` (via
``studio_project``) and serves it in Studio; the operator edits there (Studio
persists to the project files); ``sync --apply`` folds those edits back into
``edit_plan.json`` via ``studio_sync``; ``assemble.py --auto-base`` re-renders.
Studio is a review surface only — it never renders the deliverable.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

from graphics.graphics_render import HYPERFRAMES_BIN
from graphics.scene_contract import canonical_json
from graphics.scene_text_proposal import add_text_proposal_arguments, propose_text
from studio import StudioProjectError
from studio.studio_project import GenerateRequest, generate_project
from studio.review_commands import ProducerPaths, assemble_args as _assemble_args, resolve_manifest
from studio.studio_server import (
    SERVER_RECORD_NAME, StudioServerError, is_live_preview, parked_record,
    read_record, remove_record, local_sdk_environment,
)
from studio.view_manifest import MANIFEST_NAME, unsynced_changes
from stage_timing_context import timing_environment
from studio.managed_preview import open_preview, stop_preview

SYNC_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "studio_sync.py")


def _base_missing_message(paths: ProducerPaths) -> str:
    """How to create the graphics-free base this lane reviews on top of."""
    args = _assemble_args(paths)
    if "--manifest" not in args:
        args += ["--manifest", "<asset_manifest.json>"]
    return ("no base_final.mp4 — build the graphics-free base first. "
            "Smart dispatch uses render.py --skip-graphics internally and "
            "preserves the normal assembly gates:\n"
            f"  {shlex.join(args)}\n"
            "Replace any manifest placeholder with the admitted manifest path; "
            "do not rename an existing final.mp4 into the base.")


def _require_inputs(paths: ProducerPaths) -> None:
    """Fail loudly when the plan or base the view derives from is absent."""
    if not os.path.isfile(paths.plan):
        raise StudioServerError(
            f"no edit_plan.json in {paths.root} — author a plan first (/produce)")
    if not os.path.isfile(paths.base):
        raise StudioServerError(_base_missing_message(paths))


def _unsynced(studio_dir: str) -> list[str]:
    """Manifest diff, ignoring the review lane's own server record."""
    return [finding for finding in unsynced_changes(os.path.abspath(studio_dir))
            if not finding.startswith(SERVER_RECORD_NAME + ":")]


def _serve(paths: ProducerPaths) -> int:
    """Use the shared native lifecycle across every draft directory."""
    record = open_preview(paths.studio_dir)
    print(f"studio: {record.url} (pid {record.pid})")
    return 0


def cmd_open(paths: ProducerPaths, force: bool = False) -> int:
    """Generate/refresh the studio view, then serve it for review."""
    _require_inputs(paths)
    with parked_record(paths.studio_dir):
        pending = _unsynced(paths.studio_dir)
        if pending and not force:
            print("refused: studio dir has unsynced Studio edits:\n  "
                  + "\n  ".join(pending), file=sys.stderr)
            print(f"sync them (studio_review.py sync {shlex.quote(paths.root)} --apply) "
                  "or discard them (open --force)", file=sys.stderr)
            return 2
        result = generate_project(GenerateRequest(
            paths.plan, paths.base, paths.studio_dir, force=force))
    print(f"generated: {result['entries']} graphics across "
          f"{result['tracks']} lanes ({result['exitClamped']} exit-clamped)")
    return _serve(paths)


def cmd_stop(paths: ProducerPaths) -> int:
    """Verify managed shutdown before removing the local runtime pointer."""
    stop_preview(paths.studio_dir)
    record = read_record(paths.studio_dir)
    if record is not None and is_live_preview(paths.studio_dir, record):
        raise StudioServerError('Preview is outside the managed registry; adopt its exact identity before stopping')
    remove_record(paths.studio_dir)
    print('registered preview stopped; stale local pointer cleared')
    return 0


@dataclasses.dataclass(frozen=True)
class _Status:
    """The review lane's observable state for one producer dir."""

    plan_ok: bool
    base_ok: bool
    generated: bool
    live: bool
    edits: list[str]
    url: str


def _next_action(paths: ProducerPaths, state: _Status) -> str:
    """State → the one command the operator should run next."""
    root = shlex.quote(paths.root)
    if not state.plan_ok:
        return "author edit_plan.json first (the producer skill / /produce)"
    if not state.base_ok:
        return _base_missing_message(paths)
    if not state.generated:
        return f"studio_review.py open {root}"
    if state.edits and all(f.endswith(": unexpected") for f in state.edits):
        return ("only Studio-installed additions remain — sync never adopts "
                f"them (fail-closed); brain-review or open {root} --force")
    if state.edits and state.live:
        return (f"finish editing in Studio ({state.url}), then: "
                f"studio_review.py sync {root} --apply")
    if state.edits:
        return (f"studio_review.py sync {root} --apply "
                "(or open --force to discard the Studio edits)")
    if state.live:
        return (f"review at {state.url}; edit in Studio, then "
                f"sync --apply and re-assemble")
    return (f"studio_review.py open {root} to review again — or "
            "re-render the deliverable: " + shlex.join(_assemble_args(paths)))


def cmd_status(paths: ProducerPaths) -> int:
    """Report plan/base/view/server/edit state plus the next action."""
    record = read_record(paths.studio_dir)
    generated = os.path.isfile(os.path.join(paths.studio_dir, MANIFEST_NAME))
    state = _Status(
        plan_ok=os.path.isfile(paths.plan),
        base_ok=os.path.isfile(paths.base),
        generated=generated,
        live=record is not None and is_live_preview(paths.studio_dir, record),
        edits=_unsynced(paths.studio_dir) if generated else [],
        url=record.url if record else "")
    print(f"plan:    {'ok' if state.plan_ok else 'MISSING'} ({paths.plan})\n"
          f"base:    {'ok' if state.base_ok else 'MISSING'} ({paths.base})\n"
          f"studio:  {'generated' if state.generated else 'not generated'}\n"
          f"server:  {'up — ' + state.url if state.live else 'down'}\n"
          f"edits:   {len(state.edits)} unsynced"
          + (" — " + "; ".join(state.edits[:4]) if state.edits else "")
          + f"\nnext:    {_next_action(paths, state)}")
    return 0


def cmd_context(paths: ProducerPaths, fields: str | None = None) -> int:
    """Run the agent bridge against the recorded port; print its JSON."""
    record = read_record(paths.studio_dir)
    if record is None or not is_live_preview(paths.studio_dir, record):
        raise StudioServerError("no running Studio preview — run open first "
                                "(the bridge needs the recorded port)")
    node, environment = local_sdk_environment()
    args = [node, HYPERFRAMES_BIN, "preview", "--context", "--json",
            "--port", str(record.port)]
    if fields:
        args += ["--context-fields", fields]
    proc = subprocess.run(args, cwd=paths.studio_dir, capture_output=True,
                          text=True, check=False, env=environment)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_sync(paths: ProducerPaths, apply: bool = False,
             assemble: bool = False, manifest: str | None = None) -> int:
    """Pass through to studio_sync; on applied sync, chain the re-render."""
    if assemble and not apply:
        raise StudioServerError("--assemble requires --apply; no commands were run")
    if not os.path.isfile(SYNC_CLI):
        raise StudioServerError(f"sync module not present: {SYNC_CLI} — "
                                "the Studio sync lane is not in this tree")
    args = [sys.executable, SYNC_CLI, paths.studio_dir]
    if apply:
        args.append("--apply")
    resolved = resolve_manifest(paths, manifest)
    if resolved:
        args += ["--manifest", resolved]
    with parked_record(paths.studio_dir):
        code = subprocess.run(args, check=False, env=timing_environment()).returncode
    if code != 0 or not apply:
        return code
    if assemble:
        return subprocess.run(_assemble_args(paths, resolved), check=False,
                              env=timing_environment()).returncode
    print("plan updated — complete required reviews and renew stale receipts, then rebuild:")
    print("  " + shlex.join(_assemble_args(paths, resolved)))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Keep the existing review commands and discoverable proposal-only SDK alias."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add_text_proposal_arguments(sub.add_parser(
        "propose-text", help="SDK text proposal only; never apply, approve or render"))
    for name in ("open", "stop", "status", "context", "sync"):
        cmd = sub.add_parser(name)
        cmd.add_argument("producer_dir")
    sub.choices["open"].add_argument("--force", action="store_true",
                                     help="discard unsynced Studio edits")
    sub.choices["context"].add_argument("--context-fields", default=None,
                                        help="bridge fields, e.g. selection,lint")
    sub.choices["sync"].add_argument("--apply", action="store_true")
    sub.choices["sync"].add_argument(
        "--assemble", action="store_true",
        help="after a successful --apply, run assemble.py --auto-base")
    sub.choices["sync"].add_argument(
        "--manifest", default=None,
        help="asset_manifest.json override (default: beside the plan, else "
             "the workspace's <project_root>/source/asset_manifest.json)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch review operations or emit one explicitly uncommitted text proposal."""
    args = _parser().parse_args(argv)
    if args.command == "propose-text":
        try:
            sys.stdout.write(canonical_json(propose_text(args)).decode("utf-8") + "\n")
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        paths = ProducerPaths.resolve(args.producer_dir)
        if args.command == "open":
            return cmd_open(paths, force=args.force)
        if args.command == "stop":
            return cmd_stop(paths)
        if args.command == "status":
            return cmd_status(paths)
        if args.command == "context":
            return cmd_context(paths, fields=args.context_fields)
        return cmd_sync(paths, apply=args.apply, assemble=args.assemble,
                        manifest=args.manifest)
    except (StudioServerError, StudioProjectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
