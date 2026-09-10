#!/usr/bin/env python3
"""Re-measure face clearance and visual authority on a finished render."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from cut_delivery_authority import verify_delivered_cuts
from ingest_probe import probe_media
from palmier.desktop_title_card_plan import plan_title_card_shards
from planner.free_space import verify_placement
from planner.graphics_anchors import FACE_ANCHORS, valid_face_bbox


def _read(path: str, label: str) -> dict | list:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError(f"{label} must be a JSON object or array")
    return value


def _bbox(raw: object, label: str) -> tuple[float, float, float, float]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise RuntimeError(f"{label} has no four-number placed bbox")
    try:
        result = tuple(float(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} placed bbox is not numeric") from exc
    if result[2] <= result[0] or result[3] <= result[1]:
        raise RuntimeError(f"{label} placed bbox has no positive area")
    return result


def _face_aware(entry: dict, plan: dict) -> bool:
    anchor = entry.get("anchor", "free-band")
    bbox = entry.get("faceBBoxNorm")
    global_bbox = plan.get("faceBBoxNorm")
    return (
        anchor in FACE_ANCHORS
        or (
            anchor == "free-band"
            and (valid_face_bbox(bbox) or valid_face_bbox(global_bbox))
        )
    )


def _verify_window(final: str, window: tuple[float, float],
                   bbox: tuple) -> dict:
    ok, detail = verify_placement(final, window[0], window[1], bbox)
    return {"ok": bool(ok), **detail}


def _own_screen(row: dict, canvas: tuple[int, int]) -> dict:
    placed = _bbox(row.get("placedBBox"), "own-screen graphic")
    expected = (0.0, 0.0, float(canvas[0]), float(canvas[1]))
    return {"ok": placed == expected, "placedBBox": list(placed),
            "expectedBBox": list(expected)}


def _graphics(plan: dict, out_dir: str, final: str,
              canvas: tuple[int, int]) -> list[dict]:
    track = plan.get("graphicsTrack") or []
    rows = _read(
        os.path.join(out_dir, "graphics_placements.json"),
        "graphics placement authority")
    if not isinstance(rows, list) or len(rows) != len(track):
        raise RuntimeError(
            "graphics placement authority does not cover graphicsTrack")
    results = []
    for index, (entry, row) in enumerate(zip(track, rows, strict=True)):
        label = str(entry.get("id") or f"graphicsTrack[{index}]")
        anchor = entry.get("anchor", "free-band")
        if anchor == "own-screen":
            verdict = _own_screen(row, canvas)
        elif _face_aware(entry, plan):
            if row.get("expandedFace") is None:
                raise RuntimeError(
                    f"{label} lacks measured expanded-face authority")
            placed = _bbox(row.get("placedBBox"), label)
            verdict = _verify_window(
                final,
                (float(entry["outStart"]), float(entry["outEnd"])),
                placed)
        else:
            verdict = {"ok": True, "reason": "not face-aware"}
        results.append({"id": label, "anchor": anchor,
                        "region": row.get("region"), **verdict})
    return results


def _title_cards(plan: dict, out_dir: str, final: str,
                 canvas: tuple[int, int], fps: float,
                 target_frames: int) -> list[dict]:
    cards = plan.get("titleCards") or []
    if not cards:
        return []
    project = {"projectSettings": {
        "fps": fps, "width": canvas[0], "height": canvas[1],
    }}
    plan_title_card_shards(plan, out_dir, project, target_frames)
    authority = _read(
        os.path.join(out_dir, "title_card_palmier.json"),
        "title-card alpha authority")
    if not isinstance(authority, dict):
        raise RuntimeError("title-card alpha authority is malformed")
    entries = authority.get("entries")
    if not isinstance(entries, list) or len(entries) != len(cards):
        raise RuntimeError("title-card alpha authority does not cover the plan")
    results = []
    for index, (card, entry) in enumerate(zip(cards, entries, strict=True)):
        png, placement = entry.get("png") or {}, entry.get("placement") or {}
        bbox = (
            float(placement["x"]), float(placement["y"]),
            float(placement["x"]) + float(png["width"]),
            float(placement["y"]) + float(png["height"]),
        )
        verdict = _verify_window(
            final, (float(card["outStart"]), float(card["outEnd"])), bbox)
        results.append({
            "id": entry.get("elementId") or f"title-card:{index}",
            "placedBBox": list(bbox), **verdict,
        })
    return results


def run(out_dir: str) -> dict:
    """Return a machine-readable post-render geometry verdict."""
    out_dir = os.path.abspath(out_dir)
    final = os.path.join(out_dir, "final.mp4")
    plan = _read(os.path.join(out_dir, "edit_plan.json"), "render plan")
    if not isinstance(plan, dict):
        raise RuntimeError("render plan is not an object")
    media = probe_media(final)
    facts = (media.width, media.height, media.fps)
    if media.vfr or any(value is None for value in facts):
        raise RuntimeError("final has no stable CFR delivery geometry")
    canvas = int(media.width), int(media.height)
    cut = verify_delivered_cuts(out_dir, final, plan)
    graphics = _graphics(plan, out_dir, final, canvas)
    titles = _title_cards(
        plan, out_dir, final, canvas, float(media.fps), cut.frames)
    ok = all(row["ok"] for row in [*graphics, *titles])
    return {"ok": ok, "final": final, "canvas": list(canvas),
            "fps": media.fps, "cut": asdict(cut),
            "graphics": graphics, "titleCards": titles}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir")
    try:
        report = run(parser.parse_args().out_dir)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        report = {"ok": False, "error": str(exc)}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
