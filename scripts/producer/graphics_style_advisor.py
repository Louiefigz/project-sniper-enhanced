#!/usr/bin/env python3
"""Deterministically recommend a longform graphics grammar from edit context."""
from __future__ import annotations

import json
import sys

from compile_timeline import compile_plan
from edit_scope import lane_required, resolve_scope
from graphics.intro_semantic_contract import semantic_beats
from graphics.style_profiles import FACE_BRIDGE_PROFILE
from graphics_planner import output_words


def _has_face(plan: dict) -> bool:
    bbox = plan.get("faceBBoxNorm")
    return isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(
        isinstance(value, (int, float)) for value in bbox)


def recommend_style(plan: dict, beats: list[dict]) -> dict:
    """Return a persisted target recommendation plus auditable signals."""
    target = plan.get("target") or {}
    shapes = sorted({str(row.get("shape")) for row in beats if row.get("shape")})
    signals = {"semanticBeatCount": len(beats),
               "distinctInformationShapes": len(shapes),
               "informationShapes": shapes, "faceTrackAvailable": _has_face(plan)}
    active = target.get("mode") == "longform" \
        and resolve_scope(target) in ("produced", "full") \
        and lane_required(target, "graphics")
    if active and signals["faceTrackAvailable"] and len(beats) >= 8 \
            and len(shapes) >= 4:
        style = "face-bridge"
        rationale = (f"{len(beats)} strong early semantic beats across "
                     f"{len(shapes)} information shapes plus a tracked presenter "
                     "earn the two-chassis evidence-dense face bridge.")
    elif active and len(beats) >= 6 and len(shapes) >= 3:
        style = "overlay-rich"
        rationale = (f"{len(beats)} strong early semantic beats across "
                     f"{len(shapes)} information shapes earn varied overlays, "
                     "but no reliable presenter track supports the PIP chassis.")
    else:
        style = "cutaway-only"
        rationale = ("The edit lacks the combined semantic density, shape variety, "
                     "and presenter tracking required by the richer grammars.")
    fields = {"graphicsStyle": style, "graphicsStyleRationale": rationale}
    if style == "face-bridge":
        fields["visualProfile"] = FACE_BRIDGE_PROFILE
    remove = [] if style == "face-bridge" else ["visualProfile"]
    return {"recommendedTargetFields": fields, "removeTargetFields": remove,
            "signals": signals}


def build_advice(plan: dict, transcripts_dir: str, manifest: dict) -> dict:
    """Derive recommendation inputs only from the kept output timeline."""
    words = output_words(plan, transcripts_dir, manifest)
    out_dur = compile_plan(plan).output_duration
    return recommend_style(plan, semantic_beats(words, out_dur))


def _args(argv: list[str]) -> tuple[str, str, str, str | None]:
    if len(argv) not in (3, 5) or len(argv) == 5 and argv[3] != "--out":
        raise ValueError("usage: graphics_style_advisor.py <plan.json> "
                         "<transcripts_dir> <manifest.json> [--out advice.json]")
    return argv[0], argv[1], argv[2], argv[4] if len(argv) == 5 else None


def main() -> None:
    try:
        plan_path, transcripts_dir, manifest_path, out_path = _args(sys.argv[1:])
        with open(plan_path) as handle:
            plan = json.load(handle)
        with open(manifest_path) as handle:
            manifest = json.load(handle)
        advice = build_advice(plan, transcripts_dir, manifest)
        if out_path:
            with open(out_path, "w") as handle:
                json.dump(advice, handle, indent=2)
        print(json.dumps(advice, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
