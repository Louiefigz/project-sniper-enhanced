#!/usr/bin/env python3
"""study_graphics — bucket a fingerprint's states into graphic TREATMENTS.

``study_states`` yields hundreds of unique on-screen states (a captioned video
churns a new state per word). For a graphics INVENTORY the brain wants them
folded into distinct treatment types with time-ranged instances, not 500 raw
frames. This applies cheap deterministic rules to each state's signals
(face presence, mean luma, dominant colours) to bucket it, then merges
consecutive same-bucket states into instances. Buckets:

  * ``talking_head``      — a face is present (captions ride on this; caption
                            styling is a vision read, noted in the doc).
  * ``full_screen_dark``  — no face, dark frame: a dark motion-graphic slide
                            (statement card / framework diagram / title).
  * ``full_screen_bright``— no face, near-white frame: a bright takeover
                            (whiteboard board / logo card / brief flash-cut).
  * ``broll``             — no face, mid-luma frame (cutaway footage).

The type NAMES are deterministic LUMA buckets, not a taste read of each
graphic's design — dark-vs-bright cannot tell a statement card from a diagram,
so the sub-types above come from the operator's/brain's review off the contact
sheets. Emits a machine-readable inventory JSON. See docs/studies/LONGFORM_VISUAL_STUDY.md.

CLI: study_graphics.py <fingerprint.json> <out.json> [--min-instance 1.0]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

DARK_LUMA = 70          # <= ⇒ dark full-screen card
BRIGHT_LUMA = 225       # >= ⇒ white flash / bright takeover


def bucket_state(state: dict) -> str:
    """One treatment bucket for a state from its deterministic signals."""
    if state.get("face_present"):
        return "talking_head"
    luma = state.get("mean_luma") or 0.0
    if luma >= BRIGHT_LUMA:
        return "full_screen_bright"
    if luma <= DARK_LUMA:
        return "full_screen_dark"
    return "broll"


def merge_instances(states: list[dict]) -> list[dict]:
    """Collapse consecutive same-bucket states into time-ranged instances."""
    out: list[dict] = []
    for state in states:
        b = bucket_state(state)
        if out and out[-1]["type"] == b and state["t_start"] - out[-1]["end"] <= 0.75:
            inst = out[-1]
            inst["end"] = state["t_end"]
            inst["states"] += 1
            inst["_lumas"].append(state.get("mean_luma") or 0.0)
            inst["_colors"].extend(state.get("dominant_colors", [])[:2])
        else:
            out.append({"type": b, "start": state["t_start"], "end": state["t_end"],
                        "states": 1, "_lumas": [state.get("mean_luma") or 0.0],
                        "_colors": list(state.get("dominant_colors", [])[:2])})
    for inst in out:
        inst["duration"] = round(inst["end"] - inst["start"], 2)
        inst["meanLuma"] = round(sum(inst["_lumas"]) / len(inst["_lumas"]), 1)
        inst["palette"] = [c for c, _ in Counter(inst.pop("_colors")).most_common(4)]
        inst.pop("_lumas")
    return out


def summarize(instances: list[dict], min_instance: float) -> dict:
    """Type counts + total time, and the non-talking-head instances (>= min)."""
    by_type: dict[str, dict] = {}
    for inst in instances:
        agg = by_type.setdefault(inst["type"], {"count": 0, "totalDur": 0.0})
        agg["count"] += 1
        agg["totalDur"] = round(agg["totalDur"] + inst["duration"], 2)
    graphics = [i for i in instances
                if i["type"] != "talking_head" and i["duration"] >= min_instance]
    return {"byType": by_type, "graphicInstances": graphics}


def build_inventory(fingerprint_path: str, min_instance: float) -> dict:
    """Full graphics inventory for a fingerprint.json."""
    fp = json.load(open(fingerprint_path))
    states = fp["states"]
    instances = merge_instances(states)
    summary = summarize(instances, min_instance)
    return {
        "video": fp.get("video"), "states": len(states),
        "instances": len(instances), "minInstanceS": min_instance,
        **summary,
        "allInstances": [{k: v for k, v in i.items() if not k.startswith("_")}
                         for i in instances],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bucket states into graphic treatments")
    parser.add_argument("fingerprint")
    parser.add_argument("out_json")
    parser.add_argument("--min-instance", type=float, default=1.0, dest="min_instance")
    args = parser.parse_args()
    inv = build_inventory(args.fingerprint, args.min_instance)
    json.dump(inv, open(args.out_json, "w"), indent=2)
    line = {"status": "done", "states": inv["states"], "instances": inv["instances"],
            "byType": {k: v["count"] for k, v in inv["byType"].items()},
            "graphicInstances": len(inv["graphicInstances"])}
    print(json.dumps(line, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
