"""Hash-bound inputs and translated steps for Palmier working checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from fingerprints import file_sha256, plan_content_hash
from ingest_probe import probe_media
from palmier.checkpoint_plan import prepare_checkpoint_plan
from palmier.mcp_client import PalmierError
from palmier.presenter_asset import fill_presenter_assets
from palmier.translate import TranslateRequest, translate


@dataclass(frozen=True)
class CheckpointInput:
    out_dir: str
    plan_path: str
    manifest_path: str
    stage: str
    round: int
    media_path: str | None = None
    cache_dir: str | None = None


@dataclass(frozen=True)
class CheckpointAuthority:
    plan_hash: str
    manifest_hash: str
    media_hash: str | None
    checkpoint_key: str


def read_json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} is not a JSON object")
    return value


def input_authority(spec: CheckpointInput, plan: dict) -> CheckpointAuthority:
    plan_hash = plan_content_hash(plan)
    manifest_hash = file_sha256(spec.manifest_path)
    media_hash = file_sha256(spec.media_path) if spec.media_path else None
    raw = json.dumps([spec.stage, spec.round, plan_hash, manifest_hash,
                      media_hash], separators=(",", ":"))
    key = hashlib.sha256(raw.encode()).hexdigest()
    return CheckpointAuthority(plan_hash, manifest_hash, media_hash, key)


def checkpoint_label(spec: CheckpointInput,
                     authority: CheckpointAuthority) -> str:
    token = (authority.media_hash or authority.plan_hash)[:8]
    if spec.stage == "cut":
        return f"Sniper · Cut approved · {token}"
    if spec.stage == "plan":
        return f"Sniper · Plan authored · {token}"
    if spec.stage == "revision":
        return f"Sniper · Revision {spec.round} · {token}"
    return f"Sniper · Render {spec.round} (unapproved) · {token}"


def _source(manifest: dict) -> dict:
    rows = manifest.get("sources") or []
    source = next((row for row in rows if row.get("role") == "primary"),
                  rows[0] if rows else None)
    required = ("path", "fps", "resolution")
    if not isinstance(source, dict) or any(not source.get(key) for key in required):
        raise PalmierError("checkpoint manifest has no complete primary source")
    return source


def _project(name: str, source: dict, plan: dict,
             state: dict) -> dict:
    saved = state.get("projectSettings") or {}
    values = (saved.get("fps"), saved.get("width"), saved.get("height"))
    if all(not isinstance(value, bool) and isinstance(value, (int, float))
           and value > 0 for value in values):
        return {"name": name, "fps": round(float(values[0])),
                "width": int(values[1]), "height": int(values[2])}
    target = plan.get("target") or {}
    mode = target.get("mode") or target.get("aspect")
    width, height = ((1080, 1920) if mode in ("short", "9:16")
                     else source["resolution"])
    return {"name": name, "fps": round(float(source["fps"])),
            "width": int(width), "height": int(height)}


# Stage "cut" places the approved cut spine only: every other plan key stays
# out of the build, so a lane that would block a plan checkpoint (graphics,
# motion, transitions) can never block the early cut landing.
_CUT_STAGE_KEYS = ("target", "cutTrack")
_CUT_DEFERRED_LANES = ("graphicsTrack", "punchIns", "transitions", "captions",
                       "brollTrack", "reframe", "music", "audioEnhance",
                       "audioGain", "chapters", "baselineLook")


def _cut_steps(spec: CheckpointInput, plan: dict, source: dict,
               project: dict) -> tuple[list[dict], dict]:
    """Reuse the plan-stage path with a cuts-only view of the plan."""
    view = {key: plan[key] for key in _CUT_STAGE_KEYS if key in plan}
    steps, capability = _plan_steps(spec, view, source, project)
    deferred = [key for key in _CUT_DEFERRED_LANES
                if plan.get(key) not in (None, False, "", [], {})]
    if deferred:
        capability["omissions"] = [*capability["omissions"], {
            "lane": "cut-stage", "count": len(deferred),
            "reason": ("the cut checkpoint places the approved cut spine "
                       f"only; deferred lanes: {', '.join(deferred)}")}]
    return steps, capability


def _plan_steps(spec: CheckpointInput, plan: dict, source: dict,
                project: dict) -> tuple[list[dict], dict]:
    prepared = prepare_checkpoint_plan(
        plan, spec.cache_dir, fps=float(project["fps"]),
        width=int(project["width"]), height=int(project["height"]),
        source_path=os.path.abspath(source["path"]))
    graphics_cache = spec.cache_dir or os.path.dirname(
        next(iter(prepared.graphics.values()), source["path"]))
    graphics = fill_presenter_assets(
        prepared.plan, source, prepared.graphics, graphics_cache)
    request = TranslateRequest(
        fps=float(source["fps"]), source_path=os.path.abspath(source["path"]),
        graphics_paths=graphics, project_name=project["name"],
        width=project["width"], height=project["height"],
        normalize_graphics_to_canvas=True)
    capability = {"mode": "native-working-preview", "approved": False,
                  "omissions": prepared.omissions,
                  "limitations": prepared.limitations,
                  "paritySummary": prepared.parity.get("summary"),
                  "fidelityFindings": prepared.parity.get("blockers", [])}
    return translate(prepared.plan, request), capability


def _render_steps(spec: CheckpointInput, project: dict,
                  authority: CheckpointAuthority) -> tuple[list[dict], dict]:
    if not spec.media_path or not authority.media_hash:
        raise PalmierError("render checkpoint has no candidate media")
    probe = probe_media(spec.media_path)
    if any(value is None for value in (probe.duration, probe.fps,
                                        probe.width, probe.height)) or probe.vfr:
        raise PalmierError("render checkpoint media lacks stable CFR facts")
    actual = (round(float(probe.fps)), int(probe.width), int(probe.height))
    expected = (project["fps"], project["width"], project["height"])
    if actual != expected:
        raise PalmierError(f"render checkpoint canvas/fps {actual} != project {expected}")
    end = round(float(probe.duration) * project["fps"])
    steps = [
        {"op": "project", **project},
        {"op": "import", "key": "master", "path": spec.media_path},
        {"op": "mirror", "entry": {
            "mediaKey": "master", "startFrame": 0, "endFrame": end,
            "source": [0.0, float(probe.duration)], "speed": 1.0,
            "masterHash": authority.media_hash}},
    ]
    return steps, {"mode": "flat-unapproved-render", "approved": False,
                   "omissions": []}


def checkpoint_inputs(spec: CheckpointInput, state: dict) -> tuple[
        CheckpointAuthority, list[dict], dict]:
    plan = read_json(spec.plan_path, "edit plan")
    manifest = read_json(spec.manifest_path, "asset manifest")
    authority = input_authority(spec, plan)
    source = _source(manifest)
    project = _project(str(state["projectName"]), source, plan, state)
    if spec.stage == "render":
        steps, capability = _render_steps(spec, project, authority)
    elif spec.stage == "cut":
        steps, capability = _cut_steps(spec, plan, source, project)
    else:
        steps, capability = _plan_steps(spec, plan, source, project)
    return authority, steps, capability


def authority_current(spec: CheckpointInput,
                      expected: CheckpointAuthority) -> bool:
    try:
        found = input_authority(spec, read_json(spec.plan_path, "edit plan"))
    except PalmierError:
        return False
    return found == expected
