"""Shared source-template checks before any guided graphic seal or render.

Whole-program inspection is metadata/template evidence only. It does not create
runtime, source, budget, human approval or body execution authority.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import digest, read_bytes
from graphics import graphics_render
from graphics.frame_quantization import placement_frame_span
from graphics.render_rate import RenderRate, normalize_render_rate
from graphics.template_contract import composition_dimensions, planned_copy, validate_entry
from guided_opening_frames import full_program_frames
from guided_opening_inputs import OpeningInputs


@dataclass(frozen=True)
class GraphicTemplateInput:
    """The actual template bytes and complete animation intended before sealing."""

    path: Path
    sha256: str
    html: str
    rate: RenderRate
    frames: int
    dimensions: tuple[int, int]
    copy: tuple[str, ...]


def read_graphic_template(row: dict, frame_rate: str) -> GraphicTemplateInput:
    """Reuse existing copy/hold rules, native dimensions and exact frame duration."""
    entry, rate = row["entry"], normalize_render_rate(frame_rate)
    frames = row["endFrameExclusive"] - row["startFrame"]
    if placement_frame_span(entry["outStart"], entry["outEnd"], rate.numeric) != frames:
        raise RuntimeError("opening original animation duration lost its held integer frame span")
    kind = entry["kind"]
    path = Path(graphics_render.comp_path(kind))
    if path.parent != Path(graphics_render.COMPOSITIONS_DIR) or path.name != f"{kind}.html":
        raise RuntimeError("guided graphic template must be a direct registered composition")
    raw = read_bytes(path)
    html = raw.decode("utf-8")
    validate_entry(entry, html)
    return GraphicTemplateInput(path, hashlib.sha256(raw).hexdigest(), html, rate, frames,
                                composition_dimensions(html), tuple(planned_copy(entry, html)))


def inspect_full_program_graphics(inputs: OpeningInputs, guard: Callable[[], None]) -> dict:
    """Check every bound body template before spawning the FIRST body render.

    Caller supplies its real original-budget/authority guard; successful return
    cannot replace actual sealed rendering, decoded media proof or whole QC.
    Existing held document readers must also run: self-hashes are not authority.
    """
    guard()
    before = digest(inputs.documents)
    rows = full_program_frames(inputs)
    target = inputs.documents["authority"]["target"]
    canvas = (target["width"], target["height"])
    if any(type(value) is not int or value <= 0 for value in canvas):
        raise RuntimeError("guided body needs its exact positive native canvas")
    graphics, templates = [], {}
    for row in rows:
        guard()
        item = read_graphic_template(row, inputs.documents["authority"]["frameRate"])
        if item.dimensions != canvas:
            raise RuntimeError("guided body own-screen asset does not match the original full canvas")
        if item.path in templates and templates[item.path] != item.sha256:
            raise RuntimeError("guided body template changed during preflight")
        templates[item.path] = item.sha256
        graphics.append({"graphicId": row["graphicId"], "order": row["order"], "entryHash": row["entryHash"],
            "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"],
            "fullAnimationFrames": item.frames, "templatePath": str(item.path), "templateSha256": item.sha256,
            "dimensions": list(item.dimensions), "expectedCopy": list(item.copy), "frameRate": item.rate.token})
    for path, expected in templates.items():
        guard()
        if hashlib.sha256(read_bytes(path)).hexdigest() != expected:
            raise RuntimeError("guided body template changed during preflight")
    guard()
    if digest(inputs.documents) != before:
        raise RuntimeError("guided body frame/input packet changed during preflight")
    guard()
    return {"scope": "all-requested-graphic-template-preflight-not-render-or-approval",
        "graphics": graphics, "bodyRendered": False, "deliveryApproved": False}
