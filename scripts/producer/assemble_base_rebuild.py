"""Existing ordinary base rebuild lifecycle with an explicit audio policy.

This only extracts the established subprocess/refit/sidecar flow. It does not
introduce a second renderer or claim multi-file crash-atomic base promotion.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from edit.refit_authority import commit_pending
from stage_timing_context import timing_environment


@dataclass(frozen=True)
class BaseRebuild:
    """Exact existing rebuild arguments without growing orchestration signatures."""

    base: str
    plan_path: str
    plan: dict
    fingerprint_path: str | None
    manifest: str
    audio_clock_policy: str
    state: str


def _run_renderer(job: BaseRebuild, plan_path: str, base_dir: str) -> None:
    """Run the one established renderer and preserve its streamed diagnostics."""
    render_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render.py")
    process = subprocess.Popen(
        [sys.executable, render_py, plan_path, job.manifest, base_dir,
         "--skip-graphics", "--approval-dir", os.path.dirname(os.path.abspath(job.base)),
         "--audio-clock-policy", job.audio_clock_policy],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env=timing_environment())
    for line in process.stdout or []:
        if line.strip():
            print(line, end="", flush=True)
    if process.wait() != 0:
        raise RuntimeError("base rebuild failed (render.py --skip-graphics)")


def _commit(job: BaseRebuild, plan: dict, staged: str | None, base_dir: str) -> None:
    """Keep the original success-only refit and base-sidecar handoff sequence."""
    from assemble import _render_sidecars, emit
    sidecars = _render_sidecars(base_dir, os.path.dirname(os.path.abspath(job.base)), job.audio_clock_policy)
    if staged:
        if job.fingerprint_path is None:
            raise RuntimeError("a staged refit requires its original fingerprint authority")
        os.replace(staged, job.plan_path)
        commit_pending(os.path.dirname(job.fingerprint_path), job.plan_path)
        emit(status="refit_written", path=job.plan_path)
    os.replace(os.path.join(base_dir, "final.mp4"), job.base)
    for source, destination in sidecars:
        os.replace(source, destination)
    if job.fingerprint_path:
        os.replace(os.path.join(base_dir, "base.fingerprint.json"), job.fingerprint_path)
        with open(os.path.join(os.path.dirname(job.fingerprint_path), "base_plan.json"), "w") as handle:
            json.dump(plan, handle, indent=1)


def rebuild_base(job: BaseRebuild) -> tuple[dict, str]:
    """Refit when needed, execute the normal base renderer, then hand off artifacts."""
    from assemble import _refit_for_rebuild, emit
    plan, staged = job.plan, None
    if job.state == "stale" and job.fingerprint_path:
        plan, staged = _refit_for_rebuild(job.plan_path, plan, job.fingerprint_path)
    base_dir = os.path.join(os.path.dirname(os.path.abspath(job.base)), "base_work")
    os.makedirs(base_dir, exist_ok=True)
    emit(status="base_rebuild_start", manifest=job.manifest,
         note="timeline/audio fields changed — rebuilding the graphics-free base")
    _run_renderer(job, staged or job.plan_path, base_dir)
    _commit(job, plan, staged, base_dir)
    emit(status="base_rebuilt", path=job.base)
    return plan, "rebuilt"
