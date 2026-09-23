#!/usr/bin/env python3
"""Write the packaged reference library: render every beat, then the manifests.

    python3 -m release.reference_library_writer

Output: `resources/references/` (the path `src/lib/server/reference-library-paths.ts`
reads). Rewrites the whole tree from `release/reference_library_spec.py`.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from release import reference_library_spec as spec
from release.build_reference_library import ROOT, frame_records, render

OUT = ROOT / "resources" / "references"
SHORTS, LONGFORM = OUT / "shorts", OUT / "longform"
SEQ, EXP = SHORTS / "sequences", SHORTS / "expansion"
SCOPE = "original-reference-rendered-from-project-sniper-templates"


@dataclass(frozen=True)
class Beat:
    """One beat to render: where its frames go and what renders them."""

    frames_dir: Path
    stem: str
    composition: str
    variables: dict
    times: tuple[float, ...]


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_beat(beat: Beat, asset: Path | None = None) -> list[dict]:
    """Render one beat and return its recorded frames."""
    beat.frames_dir.mkdir(parents=True, exist_ok=True)
    pngs = render(beat.composition, beat.variables, beat.times, asset)
    provenance = {"composition": f"templates/motion/compositions/{beat.composition}.html",
                  "variables": beat.variables}
    return frame_records(beat.frames_dir, beat.stem, pngs, beat.times, provenance)


def _aspects(beats: list[dict]) -> list[str]:
    """Aspect of every rendered frame, stated rather than assumed (a 16:9 diagram is often
    placed inside a 9:16 Short)."""
    found = {"9:16" if f["dimensions"][1] > f["dimensions"][0] else "16:9"
             for beat in beats for f in beat["source_frames"]}
    return sorted(found)


def _beat_row(case_id: str, row: tuple, composition: str, frames: list[dict]) -> dict:
    """The case-file record for one beat."""
    beat_id, idea, visible, why = row[0], row[1], row[2], row[3]
    return {"id": f"{case_id}-{beat_id}", "spoken_idea": idea, "visible": visible,
            "why_this_picture": why, "composition": composition,
            "catalog_candidates": [composition], "source_frames": frames,
            "transfer": "Reuse the mechanism with the speaker's own words; never this copy.",
            "caution": "A rendered illustration of the mechanism, not a finished-Short benchmark."}


def sequence_case(case: dict, screen: Path | None) -> dict:
    """Render and assemble one sequence case (N)."""
    beats = []
    for row in case["beats"]:
        composition = row[6] if len(row) > 6 else case["composition"]
        beat = Beat(SEQ / "frames", f"{case['id']}-{row[0]}", composition, row[4], row[5])
        frames = render_beat(beat, screen if case.get("needs_image") else None)
        beats.append(_beat_row(case["id"], row, composition, frames))
    return {"id": case["id"], "version": spec.VERSION, "title": case["title"],
            "scope": SCOPE, "render_aspects": _aspects(beats),
            "lesson": case["lesson"], "opening": case["opening"],
            "story_arc": case["story_arc"], "payoff": case["payoff"],
            "catalog": case["catalog"], "beats": beats}


def expansion_case(case: dict) -> dict:
    """Render and assemble one expansion case (CR/LM)."""
    beats = []
    for beat_id, idea, variables, times in case["beats"]:
        beat = Beat(EXP / "frames", f"{case['id']}-{beat_id}", case["composition"], variables, times)
        frames = render_beat(beat)
        beats.append({"id": f"{case['id']}-{beat_id}", "message_paraphrase": idea,
                      "composition": case["composition"], "catalog_candidates": [case["composition"]],
                      "source_frames": frames})
    return {"id": case["id"], "version": spec.VERSION, "title": case["title"], "scope": SCOPE,
            "message": case["message"], "arc": case["arc"], "execution": case["execution"],
            "avoid": case["avoid"], "typography": case["typography"],
            "catalog": case["catalog"], "beats": beats}


def entry_record(entry: dict) -> dict:
    """Render and assemble one single-mechanism entry (A)."""
    beat = Beat(SHORTS / "frames", entry["id"], entry["composition"], entry["vars"], entry["times"])
    frames = render_beat(beat)
    return {"id": entry["id"], "version": spec.VERSION, "title": entry["title"], "scope": SCOPE,
            "story_job": entry["story_job"], "use_when": entry["use_when"],
            "do_not_use_when": entry["do_not_use_when"], "catalog": [entry["composition"]],
            "frames": frames}


def longform_case(case: dict) -> dict:
    """Render and assemble one long-form case (LF)."""
    beats = []
    for beat_id, idea, variables, times in case["beats"]:
        beat = Beat(LONGFORM / "frames", f"{case['id']}-{beat_id}", case["composition"], variables, times)
        beats.append({"id": f"{case['id']}-{beat_id}", "idea": idea,
                      "catalog_candidates": [case["composition"]], "source_frames": render_beat(beat)})
    return {"schema_version": 1, "id": case["id"], "version": spec.VERSION, "title": case["title"],
            "status": case["status"], "scope": SCOPE, "summary": case["summary"],
            "source": {"aspect": "16:9", "kind": "rendered-template"}, "beats": beats}


def build() -> dict:
    """Rebuild the whole library tree and return a count summary."""
    if OUT.exists():
        shutil.rmtree(OUT)
    expansion = [expansion_case(case) for case in spec.EXPANSION]
    screen = ROOT / expansion[0]["beats"][-1]["source_frames"][-1]["path"]
    sequences = [sequence_case(case, screen) for case in spec.SEQUENCES]
    entries = [entry_record(entry) for entry in spec.ENTRIES]
    longform = [longform_case(case) for case in spec.LONGFORM]
    from release.reference_library_docs import write_documents  # noqa: PLC0415
    write_documents(OUT, entries, sequences, expansion, longform)
    frames = sum(len(b["source_frames"]) for c in sequences + expansion + longform for b in c["beats"])
    frames += sum(len(e["frames"]) for e in entries)
    return {"entries": len(entries), "sequences": len(sequences), "expansion": len(expansion),
            "longform": len(longform), "frames": frames}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
