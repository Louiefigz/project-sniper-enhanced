#!/usr/bin/env python3
"""Labelled contact sheets of rendered-review frames for a tool-less critic.

    critic_sheets.py <request.json>

Request: ``{"frames": [{"path": abs, "label": str}], "outDir": abs, "perSheet": 4|9|16}``.
The rendered critic has no file tools; it receives still images as attachments.
When a review has more frames than can be attached one by one, this packs them,
in order, into grids of 2×2, 3×3 or 4×4 tiles, each tile captioned with its
frame number and label, and prints ``{"sheets": [{"path": ..., "labels": [...]}]}``.
Only JPEG/PNG stills are accepted; nothing else is read.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHEET_PX = 1568  # long side the providers use without downscaling
LABEL_PX = 30
MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 384
_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
FONT = Path(__file__).resolve().parents[3] / "assets" / "fonts" / "Inter-Regular.ttf"


def _still(path: str) -> Path:
    """Accept one absolute regular JPEG/PNG still, rejecting links and oversize files."""
    file = Path(path)
    info = os.lstat(file)
    if not file.is_absolute() or not os.path.isfile(file) or os.path.islink(file) \
            or not 0 < info.st_size <= MAX_FRAME_BYTES:
        raise ValueError(f"review frame is not a bounded regular file: {path}")
    with open(file, "rb") as handle:
        head = handle.read(8)
    if not any(head.startswith(magic) for magic in _MAGIC):
        raise ValueError(f"review frame is not a JPEG or PNG still: {path}")
    return file


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default()


def _tile(frame: Path, label: str, box: int, font: ImageFont.ImageFont) -> Image.Image:
    """One frame fitted into a square box above its caption band."""
    tile = Image.new("RGB", (box, box + LABEL_PX), (24, 24, 24))
    with Image.open(frame) as image:
        image = image.convert("RGB")
        image.thumbnail((box, box))
        tile.paste(image, ((box - image.width) // 2, (box - image.height) // 2))
    ImageDraw.Draw(tile).text((6, box + 4), label[:60], fill=(240, 240, 240), font=font)
    return tile


def build_sheets(frames: list[dict], out_dir: Path, per_sheet: int) -> list[dict]:
    """Pack frames in order into labelled grids written to ``out_dir``."""
    if per_sheet not in (4, 9, 16) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("contact sheet request is out of bounds")
    columns = math.isqrt(per_sheet)
    box = SHEET_PX // columns
    font = _font(18 if columns < 4 else 14)
    sheets = []
    for start in range(0, len(frames), per_sheet):
        group = frames[start:start + per_sheet]
        rows = math.ceil(len(group) / columns)
        sheet = Image.new("RGB", (box * columns, (box + LABEL_PX) * rows), (0, 0, 0))
        labels = []
        for offset, row in enumerate(group):
            label = f"#{start + offset + 1} {row['label']}"
            sheet.paste(_tile(_still(row["path"]), label, box, font),
                        ((offset % columns) * box, (offset // columns) * (box + LABEL_PX)))
            labels.append(label)
        path = out_dir / f"sheet-{len(sheets) + 1:02d}.jpg"
        sheet.save(path, "JPEG", quality=88)
        sheets.append({"path": str(path), "labels": labels})
    return sheets


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: critic_sheets.py <request.json>", file=sys.stderr)
        return 2
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(request["outDir"])
    if not out_dir.is_absolute() or not out_dir.is_dir() or any(out_dir.iterdir()):
        print("contact sheet output directory must be an existing empty absolute directory", file=sys.stderr)
        return 2
    print(json.dumps({"sheets": build_sheets(request["frames"], out_dir, int(request["perSheet"]))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
