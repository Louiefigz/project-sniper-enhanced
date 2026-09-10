#!/usr/bin/env python3
"""Render title cards as exact full-canvas alpha assets for Palmier."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction

from captions.caption_fingerprints import canonical_digest
from captions.overlays import (
    _FADE_S, _overlay_xy, _resolve_font, layout_for_canvas,
)
from cut_manifestation_authority import verify_manifestation
from fingerprints import file_sha256, write_json_atomic

TITLE_CARD_AUTHORITY_NAME = "title_card_palmier.json"
_PREFIX = "title-card-alpha-"


def _tool(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"title-card renderer cannot resolve {name}")
    resolved = os.path.realpath(path)
    return {"path": resolved, "sha256": file_sha256(resolved)}


def _font() -> dict:
    path, _kwargs, label = _resolve_font()
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        raise RuntimeError("title-card brand font has no hashable file")
    return {"label": label, "path": resolved, "sha256": file_sha256(resolved)}


def _window(card: dict, rate: Fraction, total: int) -> tuple[int, int]:
    start = round(float(card["outStart"]) * float(rate))
    end = min(round(float(card["outEnd"]) * float(rate)), total)
    if start < 0 or end <= start:
        raise RuntimeError("title card falls outside the sealed frame clock")
    return start, end


def _command(png: str, output: str, dims: tuple[int, int],
             context: dict) -> list[str]:
    frames, rate = context["frames"], context["rate"]
    token = f"{rate.numerator}/{rate.denominator}"
    layout = context["layout"]
    width, height = layout.width, layout.height
    x, y = _overlay_xy(*dims, layout)
    duration = frames / float(rate)
    fade = max(0.0, duration - _FADE_S)
    graph = (
        f"[1:v]format=rgba,fade=t=out:st={fade:.6f}:"
        f"d={_FADE_S:.6f}:alpha=1[card];"
        f"[0:v][card]overlay=x={x}:y={y}:format=auto,format=rgba[out]"
    )
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"color=c=black@0.0:s={width}x{height}:r={token},format=rgba",
        "-loop", "1", "-framerate", token, "-i", png,
        "-filter_complex", graph, "-map", "[out]", "-frames:v", str(frames),
        "-an", "-c:v", "png", "-pix_fmt", "rgba", "-r", token,
        "-fps_mode", "cfr", output,
    ]


def _probe(path: str) -> dict:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
        "-of", "json", path,
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    try:
        rows = json.loads(process.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("title-card ffprobe returned invalid JSON") from exc
    if process.returncode or len(rows) != 1:
        raise RuntimeError("title-card alpha asset cannot be decoded")
    return rows[0]


def _prove(path: str, frames: int, rate: Fraction,
           canvas: tuple[int, int]) -> dict:
    probe = _probe(path)
    expected = {
        "codec_name": "png", "pix_fmt": "rgba",
        "width": canvas[0], "height": canvas[1],
        "r_frame_rate": f"{rate.numerator}/{rate.denominator}",
        "nb_read_frames": str(frames),
    }
    if any(probe.get(key) != value for key, value in expected.items()):
        raise RuntimeError(
            f"title-card alpha media differs from contract: {probe!r}")
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-vf",
        "select=eq(n\\,0),alphaextract,signalstats,"
        "metadata=print:key=lavfi.signalstats.YMAX:file=-",
        "-frames:v", "1", "-f", "null", "-",
    ], capture_output=True, text=True)
    text = process.stdout + process.stderr
    if process.returncode or "lavfi.signalstats.YMAX=" not in text:
        raise RuntimeError("title-card asset has no proved visible first frame")
    return expected


def _render_one(
        out_dir: str, card: dict, built: dict,
        context: dict) -> dict:
    png, dims = built["png"], tuple(built["dims"])
    start, end = _window(card, context["rate"], context["totalFrames"])
    identity = canonical_digest("sniper-title-card-alpha-media-v1", {
        "card": card, "pngSha256": file_sha256(png),
        "startFrame": start, "endFrame": end,
        "rendererHash": context["rendererHash"],
    })
    output = os.path.join(out_dir, f"{_PREFIX}{identity}.mov")
    render_context = {
        **context, "frames": end - start,
    }
    command = _command(png, output, dims, render_context)
    descriptor, staged = tempfile.mkstemp(
        prefix=".title-card.", suffix=".mov", dir=out_dir)
    os.close(descriptor)
    os.remove(staged)
    command[-1] = staged
    try:
        process = subprocess.run(command, capture_output=True, text=True)
        if process.returncode:
            raise RuntimeError(
                "title-card alpha render failed: " + process.stderr[-500:])
        stream = _prove(
            staged, end - start, context["rate"],
            (context["layout"].width, context["layout"].height))
        os.replace(staged, output)
    finally:
        if os.path.exists(staged):
            os.remove(staged)
    return {
        "elementId": f"title-card:{context['index']}",
        "startFrame": start, "endFrameExclusive": end,
        "text": card["text"], "png": {
            "path": os.path.abspath(png), "sha256": file_sha256(png),
            "width": dims[0], "height": dims[1]},
        "placement": {
            "x": _overlay_xy(*dims, context["layout"])[0],
            "y": _overlay_xy(*dims, context["layout"])[1]},
        "fadeOutSeconds": _FADE_S,
        "media": {"path": output, "sha256": file_sha256(output)},
        "stream": stream, "renderCommand": [*command[:-1], output],
    }


def _renderer(layout: object) -> tuple[dict, dict, str]:
    font = _font()
    tools = {"ffmpeg": _tool("ffmpeg"), "ffprobe": _tool("ffprobe")}
    digest = canonical_digest("sniper-title-card-renderer-v1", {
        "font": font, "tools": tools, "codec": "png",
        "pixelFormat": "rgba", "fadeOutSeconds": _FADE_S,
        "canvas": [layout.width, layout.height],
        "safe": layout.safe, "visualCenterX": layout.visual_center_x,
        "yRange": list(layout.y_range),
    })
    return font, tools, digest


def materialize_title_card_shards(
        plan: dict, out_dir: str,
        built_cards: list[dict]) -> dict | None:
    """Render and seal every title card during the production overlay stage."""
    cards = plan.get("titleCards") or []
    if not cards:
        return None
    out_dir = os.path.abspath(out_dir)
    if len(cards) != len(built_cards):
        raise RuntimeError("built title-card PNGs do not cover the plan")
    manifestation = verify_manifestation(out_dir, plan)
    rate = Fraction(manifestation["frameRate"])
    canvases = {
        tuple(row.get("canvas") or []) for row in built_cards
        if isinstance(row, dict)}
    if len(canvases) != 1 or len(next(iter(canvases), ())) != 2:
        raise RuntimeError("title-card build has no unique delivery canvas")
    canvas = next(iter(canvases))
    layout = layout_for_canvas(int(canvas[0]), int(canvas[1]))
    font, tools, renderer_hash = _renderer(layout)
    entries = []
    for index, (card, built) in enumerate(
            zip(cards, built_cards, strict=True)):
        context = {
            "index": index, "rate": rate,
            "totalFrames": manifestation["concat"]["videoFrames"],
            "rendererHash": renderer_hash, "layout": layout,
        }
        entries.append(_render_one(out_dir, card, built, context))
    payload = {
        "schemaVersion": 1, "kind": "title-card-alpha-authority",
        "fidelity": "baked-regenerable", "editableText": False,
        "planTitleCardsHash": canonical_digest(
            "sniper-title-card-plan-v1", cards),
        "manifestationReceiptHash": manifestation["receiptHash"],
        "timelineMapSha256": manifestation["timelineMapSha256"],
        "frameRate": manifestation["frameRate"],
        "canvas": {"width": layout.width, "height": layout.height},
        "rendererHash": renderer_hash, "font": font, "tools": tools,
        "entries": entries,
    }
    receipt = {**payload, "authorityHash": canonical_digest(
        "sniper-title-card-alpha-authority-v1", payload)}
    write_json_atomic(
        os.path.join(out_dir, TITLE_CARD_AUTHORITY_NAME), receipt, indent=2)
    return receipt
