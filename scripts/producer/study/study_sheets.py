#!/usr/bin/env python3
"""study_sheets — chronological 4x3 contact sheets of a fingerprint's states.

The graphics review is a taste read the brain/operator does by eye, so it needs
the unique on-screen states (``study_states`` reps) laid out compactly in time
order with each tile labelled by index / timestamp / signals. This tiles the
representative JPGs named in a ``fingerprint.json`` into ``sheet_NN.jpg`` grids.
Pure layout (PIL) — no judgement. Run with the venv python.

CLI: study_sheets.py <fingerprint.json> <out_dir> [--cols 4] [--rows 3]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

TILE_W, TILE_H = 480, 270          # 16:9 thumbnail per state
PAD, LABEL_H = 6, 22               # gutter + label strip height


def _label(state: dict) -> str:
    """One-line tile caption: index, timestamp, face/busy signals."""
    face = "F" if state.get("face_present") else "-"
    return (f"#{state['index']}  {state['t_start']:.1f}s  {face} "
            f"b{state.get('busy_frac', 0):.2f} {state.get('duration', 0):.1f}s")


def _tile(state: dict) -> "Image.Image":
    """Render one labelled tile for a state (grey placeholder if unreadable)."""
    cell = Image.new("RGB", (TILE_W, TILE_H + LABEL_H), (18, 18, 18))
    try:
        with Image.open(state["rep_path"]) as im:
            thumb = im.convert("RGB")
            thumb.thumbnail((TILE_W, TILE_H))
            cell.paste(thumb, ((TILE_W - thumb.width) // 2, (TILE_H - thumb.height) // 2))
    except (OSError, KeyError):
        pass
    draw = ImageDraw.Draw(cell)
    draw.rectangle([0, TILE_H, TILE_W, TILE_H + LABEL_H], fill=(30, 30, 30))
    draw.text((5, TILE_H + 5), _label(state), fill=(220, 220, 220))
    return cell


def build_sheets(states: list[dict], out_dir: str, cols: int, rows: int) -> list[str]:
    """Tile states into ``cols``x``rows`` sheets; return the written sheet paths."""
    os.makedirs(out_dir, exist_ok=True)
    per = cols * rows
    cw, ch = TILE_W + PAD, TILE_H + LABEL_H + PAD
    paths: list[str] = []
    for page, start in enumerate(range(0, len(states), per)):
        chunk = states[start:start + per]
        sheet = Image.new("RGB", (cols * cw + PAD, rows * ch + PAD), (10, 10, 10))
        for i, state in enumerate(chunk):
            r, c = divmod(i, cols)
            sheet.paste(_tile(state), (PAD + c * cw, PAD + r * ch))
        dst = os.path.join(out_dir, f"sheet_{page:02d}.jpg")
        sheet.save(dst, quality=80)
        paths.append(dst)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronological contact sheets of states")
    parser.add_argument("fingerprint")
    parser.add_argument("out_dir")
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--rows", type=int, default=3)
    args = parser.parse_args()
    states = json.load(open(args.fingerprint))["states"]
    paths = build_sheets(states, args.out_dir, args.cols, args.rows)
    print(json.dumps({"status": "done", "sheets": len(paths), "states": len(states),
                      "dir": args.out_dir}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
