"""Real 1920→3840 own-screen placement proof for the P4 exit cohort."""
from __future__ import annotations

import json
from pathlib import Path

from audit.audit_checks import FAIL
from audit.audit_placements import check_eye_trace
from graphics.graphics_stage import GraphicsJob, run_graphics_stage
from tests.p4_exit_media import (
    ProgramSpec,
    cache_media,
    file_identity,
    frame_green_border_fraction,
    make_program,
    prove_decode,
)


def _track() -> list[dict]:
    return [{
        "kind": "color-wash", "anchor": "own-screen",
        "outStart": 0.25, "outEnd": 1.25,
        "spec": {
            "accent": "#054BC9", "accent2": "#6D3BE0", "dir": "ltr",
        },
    }]


def run_geometry_case(root: Path) -> dict:
    """Render, decode, audit, and pixel-measure a real 4K composite."""
    source, output = root / "source-4k.mp4", root / "placed-4k.mp4"
    placements, cache = root / "graphics_placements.json", root / "cache-4k"
    cache.mkdir()
    make_program(
        source, ProgramSpec((3840, 2160), 24, 1.5, pattern="green"))
    track = _track()
    stage = run_graphics_stage(GraphicsJob(
        str(source), str(output), track, str(cache),
        placements_out=str(placements)))
    decoded = prove_decode(output)
    rows = json.loads(placements.read_text(encoding="utf-8"))
    audits = check_eye_trace({"graphicsTrack": track}, str(root))
    pre_source = frame_green_border_fraction(source, 2)
    pre_output = frame_green_border_fraction(output, 2)
    active_output = frame_green_border_fraction(output, 18)
    rendered_media = cache_media(cache)
    rendered_facts = prove_decode(cache / next(iter(rendered_media)))
    passed = (
        stage["frames_in"] == stage["frames_out"]
        and decoded["width"] == 3840 and decoded["height"] == 2160
        and len(rows) == 1
        and rows[0]["placedBBox"] == [0, 0, 3840, 2160]
        and rows[0]["canvas"] == [3840, 2160]
        and all(row.status != FAIL for row in audits)
        and pre_source >= 0.98 and pre_output >= 0.98
        and active_output <= 0.01
        and rendered_facts["width"] == 1920
        and rendered_facts["height"] == 1080
    )
    return {
        "passed": passed,
        "source": prove_decode(source),
        "output": decoded,
        "authoredComposition": rendered_facts,
        "placedBBox": rows[0]["placedBBox"],
        "deliveryCanvas": rows[0]["canvas"],
        "placementAudit": [
            {"name": row.name, "status": row.status} for row in audits],
        "greenBorderFractions": {
            "sourceBeforeWindow": pre_source,
            "outputBeforeWindow": pre_output,
            "outputInsideWindow": active_output,
        },
        "sourceIdentity": file_identity(source),
        "outputIdentity": file_identity(output),
    }
