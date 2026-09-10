"""Use held ordinary placement observations, never spec-supplied text geometry."""
from __future__ import annotations

import hashlib
import json
import math
import stat
from dataclasses import dataclass, field
from pathlib import Path

from audit.audit_placements import _placement_error
from cut_preview_io import read_bytes


@dataclass
class PlateContext:
    """Read-only candidate evidence; integrity binding is not QC approval."""
    rows: list = field(default_factory=list)
    graphics: list = field(default_factory=list)
    samples: list = field(default_factory=list)
    error: str = "missing actual graphics placement evidence"
    documents: list = field(default_factory=list)
    media: list = field(default_factory=list)


def _stamp(path: Path) -> tuple:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_size <= 0:
        raise ValueError("contrast reference/final is not a regular nonempty file")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _document(path: Path) -> tuple:
    raw = read_bytes(path, 1024 * 1024)
    return json.loads(raw), (path, hashlib.sha256(raw).hexdigest())


def _validate_rows(plan: dict, rows: object) -> None:
    graphics = plan.get("graphicsTrack") or []
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("placement evidence is not an array of observations")
    error = _placement_error(plan, rows)
    if error:
        raise ValueError(error)
    for graphic, row in zip(graphics, rows):
        expected = {"kind": graphic["kind"], "anchor": graphic.get("anchor", "free-band"),
                    "outStart": graphic["outStart"], "outEnd": graphic["outEnd"]}
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("placement evidence belongs to a different graphic/window/order")
        canvas = row.get("canvas")
        if not isinstance(canvas, list) or len(canvas) != 2 or any(type(v) is not int or v <= 0 for v in canvas):
            raise ValueError("placement evidence has invalid decoded canvas")
        x0, y0, x1, y1 = row["placedBBox"]
        if not 0 <= x0 < x1 <= canvas[0] or not 0 <= y0 < y1 <= canvas[1]:
            raise ValueError("placement observation lies outside the decoded canvas")


def observe_placements(out_dir: str, plan: dict, reference: str) -> PlateContext:
    """Hold exact current plan/placement bytes and media file identities once."""
    context = PlateContext(graphics=plan.get("graphicsTrack") or [])
    try:
        root = Path(out_dir).resolve(strict=True)
        current, plan_binding = _document(root / "edit_plan.json")
        rows, row_binding = _document(root / "graphics_placements.json")
        if current != plan:
            raise ValueError("contrast plan changed or belongs to another candidate")
        _validate_rows(plan, rows)
        paths = (Path(reference).resolve(strict=True), root / "final.mp4")
        context.media = [(path, _stamp(path)) for path in paths]
        context.rows, context.documents = rows, [plan_binding, row_binding]
        context.error = ""
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        context.error = str(error)
    return context


def binding_error(context: PlateContext) -> str:
    """Detect evidence changed during measurement; never write/repair sidecars."""
    if context.error:
        return context.error
    try:
        for path, expected in context.documents:
            if hashlib.sha256(read_bytes(path, 1024 * 1024)).hexdigest() != expected:
                return "contrast plan/placement bytes changed during measurement"
        if any(_stamp(path) != expected for path, expected in context.media):
            return "contrast source/base/final file identity changed during measurement"
    except (OSError, RuntimeError, ValueError) as error:
        return str(error)
    return ""


def _overlap(left: list, right: list) -> bool:
    return left[0] < right[2] and right[0] < left[2] and left[1] < right[3] and right[1] < left[3]


def cropped_samples(index: int, context: PlateContext) -> list:
    """Crop to the landed bbox; later stable-start-sorted layers may occlude."""
    if context.error or index >= len(context.rows):
        raise ValueError(context.error or "missing graphic placement observation")
    row, graphic = context.rows[index], context.graphics[index]
    order = (float(graphic["outStart"]), index)
    samples = []
    for label, timestamp, pair in context.samples:
        above = [(other, observed) for n, (other, observed) in enumerate(zip(context.graphics, context.rows))
                 if (float(other["outStart"]), n) > order and other["outStart"] <= timestamp <= other["outEnd"]]
        if any(other.get("anchor") == "focus-shift" or other.get("takeoverBase")
               or _overlap(row["placedBBox"], observed["placedBBox"]) for other, observed in above):
            raise ValueError("later/above graphic obscures intended text region; contrast attribution is ambiguous")
        expected = tuple(row["canvas"])
        if any(image.info.get("sniperOriginalSize", image.size) != expected for image in pair):
            raise ValueError("placement canvas differs from actual decoded frame dimensions")
        x0, y0, x1, y1 = row["placedBBox"]
        width, height = pair[0].size
        box = (math.floor(x0 * width / expected[0]), math.floor(y0 * height / expected[1]),
               math.ceil(x1 * width / expected[0]), math.ceil(y1 * height / expected[1]))
        samples.append((label, timestamp, tuple(image.crop(box) for image in pair)))
    return samples
