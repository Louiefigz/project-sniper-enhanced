#!/usr/bin/env python3
"""Render Desktop hole-comps with their live presenter already filled."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

from fingerprints import file_sha256
from graphics.asset_proof import prove_rendered_asset
from graphics.pip_hole import (crop_for_hole, delivery_hole_rect,
                               entry_has_hole)
from palmier.mcp_client import PalmierError

_CANVAS = (1920, 1080)
_VERSION = 1


@dataclass(frozen=True)
class PresenterRequest:
    """Inputs for one isolated Desktop presenter-card render."""

    plan: dict
    source: dict
    entry: dict
    rendered: dict
    cache_dir: str


def primary_source(manifest: dict) -> dict:
    """Return the single source authorized to fill Desktop presenter holes."""
    rows = manifest.get("sources") or []
    source = next((row for row in rows if row.get("role") == "primary"),
                  rows[0] if rows else None)
    if not isinstance(source, dict) or not source.get("id") or not source.get("path"):
        raise PalmierError("presenter card manifest has no primary source")
    return source


def _source_slices(plan: dict, entry: dict) -> list[dict]:
    """Map one output window to exact source-time spans across the cut spine."""
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    cursor, slices = 0.0, []
    for row in plan.get("cutTrack") or []:
        speed = float(row.get("speed", 1.0) or 1.0)
        duration = (float(row["end"]) - float(row["start"])) / speed
        overlap_start, overlap_end = max(start, cursor), min(end, cursor + duration)
        if overlap_end > overlap_start:
            slices.append({
                "sourceId": str(row["sourceId"]), "speed": speed,
                "start": float(row["start"]) + (overlap_start - cursor) * speed,
                "end": float(row["start"]) + (overlap_end - cursor) * speed,
            })
        cursor += duration
    covered = sum((row["end"] - row["start"]) / row["speed"] for row in slices)
    if abs(covered - (end - start)) > 0.002:
        raise PalmierError(
            f"presenter card {entry.get('id')!r} is not fully covered by cutTrack")
    return slices


def _source_dimensions(source: dict) -> tuple[int, int]:
    value = source.get("resolution")
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    from graphics.pip_takeover import probe_dims
    return probe_dims(str(source.get("path") or ""))


def _face_cx(request: PresenterRequest) -> float:
    value = request.entry.get("faceCx")
    if value is None:
        box = request.plan.get("faceBBoxNorm")
        value = float(box[0]) + float(box[2]) / 2.0 \
            if isinstance(box, list) and len(box) == 4 else 0.5
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not 0.0 <= float(value) <= 1.0:
        raise PalmierError(f"presenter card faceCx is invalid: {value!r}")
    return float(value)


def _alpha_facts(rendered: dict) -> tuple[dict, int, float]:
    proof = rendered.get("proof")
    asset = proof.get("asset") if isinstance(proof, dict) else None
    if not isinstance(asset, dict):
        raise PalmierError("presenter card has no alpha-asset proof")
    frames, duration = int(asset.get("frameCount") or 0), float(asset.get("durationS") or 0)
    if frames <= 0 or duration <= 0:
        raise PalmierError("presenter card alpha proof has no duration or frames")
    return asset, frames, frames / duration


def _render_key(request: PresenterRequest, slices: list[dict], crop: tuple) -> str:
    asset, frames, fps = _alpha_facts(request.rendered)
    source_hash = request.source.get("contentHash")
    if not isinstance(source_hash, str) or not source_hash:
        source_hash = file_sha256(str(request.source["path"]))
    payload = {"version": _VERSION, "card": asset.get("sha256"),
               "source": source_hash, "slices": slices, "crop": list(crop),
               "hole": list(delivery_hole_rect(request.entry["kind"], *_CANVAS)),
               "frames": frames, "fps": round(fps, 6)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _slice_graph(slices: list[dict], crop: tuple, size: tuple,
                 fps: float) -> tuple[list[str], str]:
    cw, ch, cx, cy = crop
    hw, hh = size
    parts: list[str] = []
    labels = ["[1:v]"] if len(slices) == 1 else [f"[src{i}]" for i in range(len(slices))]
    if len(slices) > 1:
        parts.append(f"[1:v]split={len(slices)}" + "".join(labels))
    outputs = []
    for index, (label, row) in enumerate(zip(labels, slices)):
        out = f"[presenter{index}]"
        parts.append(
            f"{label}trim=start={row['start']:.9f}:end={row['end']:.9f},"
            f"setpts=(PTS-STARTPTS)/{row['speed']:.9f},"
            f"crop={cw}:{ch}:{cx}:{cy},scale={hw}:{hh}:flags=lanczos,"
            f"setsar=1,fps={fps:.9f},format=yuv444p{out}")
        outputs.append(out)
    if len(outputs) == 1:
        return parts, outputs[0]
    parts.append("".join(outputs) + f"concat=n={len(outputs)}:v=1:a=0[presenter]")
    return parts, "[presenter]"


def _filter_graph(request: PresenterRequest, slices: list[dict],
                  crop: tuple, fps: float, duration: float) -> str:
    hx, hy, hw, hh = delivery_hole_rect(request.entry["kind"], *_CANVAS)
    parts, presenter = _slice_graph(slices, crop, (hw, hh), fps)
    parts.extend([
        f"{presenter}tpad=stop_mode=clone:stop_duration=0.1,"
        f"trim=duration={duration:.9f}[presenterfill]",
        f"color=c=black:s={_CANVAS[0]}x{_CANVAS[1]}:r={fps:.9f}:"
        f"d={duration:.9f}[canvas]",
        f"[canvas][presenterfill]overlay=x={hx}:y={hy}:eof_action=repeat[under]",
        "[under][0:v]overlay=x=0:y=0:format=auto:eof_action=repeat,"
        "format=yuva444p10le[out]",
    ])
    return ";".join(parts)


def _render(request: PresenterRequest, output: str, graph: str,
            frames: int, fps: float) -> None:
    directory = os.path.dirname(output)
    handle = tempfile.NamedTemporaryFile(
        dir=directory, prefix=os.path.basename(output) + ".", suffix=".tmp.mov",
        delete=False)
    temporary = handle.name
    handle.close()
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
           "-i", request.rendered["path"], "-i", request.source["path"],
           "-filter_complex", graph, "-map", "[out]", "-an", "-r", f"{fps:.9f}",
           "-frames:v", str(frames), "-c:v", "prores_ks", "-profile:v", "4444",
           "-pix_fmt", "yuva444p10le", temporary]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise PalmierError(
                "presenter-card render failed: " + proc.stderr.strip()[-500:])
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def fill_presenter_entry(request: PresenterRequest) -> dict:
    """Return the normal graphic, or an opaque-in-alpha presenter-filled MOV."""
    if not entry_has_hole(request.entry):
        return request.rendered
    source_path = request.source.get("path")
    if not isinstance(source_path, str) or not os.path.isfile(source_path):
        raise PalmierError(f"presenter-card source is missing: {source_path!r}")
    slices = _source_slices(request.plan, request.entry)
    expected_id = str(request.source.get("id") or "")
    if not expected_id or any(row["sourceId"] != expected_id for row in slices):
        raise PalmierError("presenter card crosses a non-primary source")
    width, height = _source_dimensions(request.source)
    crop = crop_for_hole(width, height, request.entry["kind"], _face_cx(request))
    asset, frames, fps = _alpha_facts(request.rendered)
    duration = frames / fps
    key = _render_key(request, slices, crop)
    output = os.path.join(request.cache_dir, f"{key}.mov")
    cached = os.path.isfile(output)
    if not cached:
        graph = _filter_graph(request, slices, crop, fps, duration)
        _render(request, output, graph, frames, fps)
    proof_entry = {**request.entry, "presenterFilled": True}
    proof = prove_rendered_asset(
        output, proof_entry, "mov", _CANVAS,
        float(request.entry["outEnd"]) - float(request.entry["outStart"]), key)
    return {"path": output, "cached": cached, "key": key,
            "kind": request.entry["kind"], "fmt": "mov", "proof": proof,
            "presenterFill": {"sourceSlices": slices, "crop": list(crop),
                              "hole": list(delivery_hole_rect(
                                  request.entry["kind"], *_CANVAS))}}


def fill_presenter_assets(plan: dict, source: dict, graphics: dict[int, str],
                          cache_dir: str) -> dict[int, str]:
    """Replace active hole-comp paths with isolated presenter-filled assets."""
    result = dict(graphics)
    for index, entry in enumerate(plan.get("graphicsTrack") or []):
        path = graphics.get(index)
        if not path or not entry_has_hole(entry):
            continue
        proof_path = path + ".proof.json"
        if not os.path.isfile(proof_path):
            raise PalmierError(f"presenter card proof is missing: {proof_path}")
        with open(proof_path, encoding="utf-8") as handle:
            proof = json.load(handle)
        rendered = {"path": path, "proof": proof, "kind": entry["kind"],
                    "fmt": "mov"}
        request = PresenterRequest(plan, source, entry, rendered, cache_dir)
        result[index] = fill_presenter_entry(request)["path"]
    return result
