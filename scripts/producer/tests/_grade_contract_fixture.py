"""Synthetic supplied records only: no claim these fixtures came from a decoder."""
from __future__ import annotations

from fractions import Fraction

from color.grade_contract import POLICY
from color.grade_source_class import ERROR_POLICY
from cut_preview_io import digest

COLOR = {"pixelFormat": "yuv420p", "range": "tv", "matrix": "bt709",
         "primaries": "bt709", "transfer": "bt709", "hdrSignaled": False}


def declaration(count: int = 300) -> dict:
    """Declare one complete source-frame lighting group, explicitly neutral."""
    return {"schemaVersion": 1, "sourceId": "raw-1", "sourceProfile": "bt709-sdr",
            "cameraProfile": None, "historyState": "known", "transformHistory": [],
            "lightingGroups": [{"id": "room", "startFrame": 0, "endFrame": count,
                                "intent": "neutral", "description": "Synthetic neutral ramp"}]}


def binding(context: dict | None = None, fps: str = "30000/1001") -> dict:
    """Current observer-like fixture identity; never a real ingest receipt."""
    context = context or declaration()
    count = context["lightingGroups"][-1]["endFrame"]
    return {"sourceId": "raw-1", "sourceSha256": "a" * 64,
            "admissionReceiptSha256": "b" * 64, "projectHistorySha256": "c" * 64,
            "declarationSha256": digest(context), "fps": fps, "frameCount": count}


def recipe(source: dict | None = None, context: dict | None = None) -> dict:
    """Explicit private intent, with one identity correction per declared group."""
    context = context or declaration()
    return {"schemaVersion": 1, "kind": POLICY, "source": source or binding(context),
            "corrections": [{"groupId": group["id"], "encodedLumaOffset": 0,
                             "contrast": 1, "saturation": 1}
                            for group in context["lightingGroups"]],
            "look": {"name": "neutral", "intensity": 0}}


def stream(source: dict | None = None, origin: int = 900_000) -> dict:
    """Use a real rational clock shape with a nonzero first timestamp."""
    source = source or binding()
    rate = Fraction(source["fps"])
    return {**COLOR, "videoStreamCount": 1, "streamIndex": 0,
            "fps": source["fps"], "timeBase": f"1/{rate.numerator}",
            "firstPts": origin, "frameCount": source["frameCount"],
            "width": 1920, "height": 1080, "progressive": True}


def frame(index: int, observed: dict | None = None) -> dict:
    """Project one complete unconverted decoded-frame record."""
    observed = observed or stream()
    step = int(1 / (Fraction(observed["fps"]) * Fraction(observed["timeBase"])))
    return {**COLOR, "index": index, "streamIndex": observed["streamIndex"],
            "pts": observed["firstPts"] + index * step, "durationTicks": step,
            "width": observed["width"], "height": observed["height"],
            "interlaced": False, "repeatPict": 0, "corrupt": None, "decodeErrorFlags": None}


def terminal(source: dict | None = None) -> dict:
    """Supplied terminal facts; pure validation does not authenticate these."""
    return {"source": source or binding(), "reachedEof": True,
            "decoderExitCode": 0, "decoderErrorCount": 0, "decoderWarningCount": 0,
            "decoderErrorObservationPolicy": ERROR_POLICY}
