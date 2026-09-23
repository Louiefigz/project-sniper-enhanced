#!/usr/bin/env python3
"""Deterministically recommend a longform graphics grammar from edit context."""
from __future__ import annotations

import json
import sys

from compile_timeline import compile_plan
from graphics.intro_semantic_contract import semantic_beats
from graphics_planner import output_words


def recommend_style(plan: dict, beats: list[dict]) -> dict:
    """Recommend catalog selection without inferring a reference style."""
    return {"recommendedTargetFields": {"graphicsStyle": "catalog-first",
            "graphicsStyleRationale": "Inspect the upstream HyperFrames catalog for each visual need."},
            "removeTargetFields": ["style", "visualProfile"],
            "signals": {"semanticBeatCount": len(beats), "sourcePolicy": "hyperframes-catalog-first-v1"}}



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
