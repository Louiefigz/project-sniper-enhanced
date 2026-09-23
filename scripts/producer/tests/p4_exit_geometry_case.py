"""P4 v2 actual catalog portrait 1080x1920→2160x3840 placement proof."""
from __future__ import annotations

import json
from pathlib import Path

from audit.audit_placements import check_eye_trace
from graphics.graphics_stage import GraphicsJob, run_graphics_stage
from tests.p4_exit_media import (
    ProgramSpec, cache_media, file_identity, frame_card_geometry,
    frame_green_border_fraction, make_program, prove_decode,
)


def _track() -> list[dict]:
    """Two held lines expose settled artwork before and after the swap."""
    return [{"kind": "line-swap", "anchor": "own-screen",
             "outStart": 0.25, "outEnd": 3.75,
             "spec": {"lineA": "FIRST LINE", "lineB": "SECOND LINE",
                      "swapAt": 1.5, "underlineWord": "", "exit": "hold"}}]


def _pixels(source: Path, output: Path, native: Path) -> dict:
    """Separate opaque canvas replacement from actual internal artwork scale."""
    edges = {"sourceBeforeWindow": frame_green_border_fraction(source, 2),
             "outputBeforeWindow": frame_green_border_fraction(output, 2),
             "outputAfterWindow": frame_green_border_fraction(output, 94),
             "outputFirstHold": frame_green_border_fraction(output, 30),
             "outputSecondHold": frame_green_border_fraction(output, 66)}
    cards = [{"native": frame_card_geometry(native, local, 1),
              "delivery": frame_card_geometry(output, global_frame, 2)}
             for local, global_frame in ((24, 30), (60, 66))]
    scaled = all(all(abs(delivery / 2 - native_value) <= 3 for delivery, native_value in zip(
        row["delivery"]["whiteBBox"], row["native"]["whiteBBox"])) for row in cards)
    return {"greenBorderFractions": edges, "cardGeometry": cards,
            "nativeToDeliveryBoundsMatch": scaled,
            "passed": min(edges[name] for name in (
                "sourceBeforeWindow", "outputBeforeWindow", "outputAfterWindow")) >= 0.98
            and max(edges["outputFirstHold"], edges["outputSecondHold"]) <= 0.01
            and scaled and all(row["native"]["passed"] and row["delivery"]["passed"] for row in cards)}


def run_geometry_case(root: Path) -> dict:
    """Render through real source admission; full-decode and measure both holds."""
    source, output = root / "source-portrait-4k.mp4", root / "placed-portrait-4k.mp4"
    placements, cache = root / "graphics_placements.json", root / "cache-4k"
    cache.mkdir()
    make_program(source, ProgramSpec((2160, 3840), 24, 4.0, pattern="green"))
    track = _track()
    stage = run_graphics_stage(GraphicsJob(str(source), str(output), track, str(cache),
                                          placements_out=str(placements)))
    decoded = prove_decode(output)
    rows = json.loads(placements.read_text(encoding="utf-8"))
    if len(rows) != 1:
        raise RuntimeError("catalog geometry requires exactly one placement")
    rendered_media = cache_media(cache)
    if len(rendered_media) != 1:
        raise RuntimeError("catalog geometry requires exactly one native cached clip")
    native = cache / next(iter(rendered_media))
    rendered = prove_decode(native)
    pixels = _pixels(source, output, native)
    audits = check_eye_trace({"graphicsTrack": track}, str(root))
    passed = (stage["frames_in"] == stage["frames_out"] == decoded["decodedFrames"] == 96
              and [decoded["width"], decoded["height"]] == [2160, 3840]
              and [rendered["width"], rendered["height"]] == [1080, 1920]
              and rendered["decodedFrames"] == 84
              and decoded["frameRate"] == rendered["frameRate"] == "24/1"
              and rows[0]["placedBBox"] == [0, 0, 2160, 3840]
              and rows[0]["canvas"] == [2160, 3840]
              and all(row.status == "pass" for row in audits) and pixels["passed"])
    return {**pixels, "passed": passed, "source": prove_decode(source), "output": decoded,
            "geometryPolicy": "line-swap-portrait-own-screen-2x-v2",
            "authoredComposition": rendered, "placedBBox": rows[0]["placedBBox"],
            "deliveryCanvas": rows[0]["canvas"],
            "placementAudit": [{"name": row.name, "status": row.status} for row in audits],
            "sourceIdentity": file_identity(source), "outputIdentity": file_identity(output)}
