"""Actual V8 request/window rederivation and a local prior-lane validation view.

The geometry gate is intentionally narrower than TS authoring: it reuses the
existing executor canvas/no-upscale policy. Its yuv420p argument is a declared
execution policy, never an observation of source, presentation or output media.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy

from contracts.schema_validator import validate_document
from cut_preview_io import digest
from graphics.presenter_layout_contract import PresenterCanvas, integer, number, presenter_identifier
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_proposal_reframe import _parse, proposal_trim

V8_SCHEMA = "treatment-proposal-v8.schema.json"
_TIMED = frozenset({"beatIndex", "startAnchor", "endAnchorExclusive", "reason", "presenterLayout"})


def _layout_operation(row: dict, beats: list) -> dict:
    """Validate the actual timed fields before constructing a local no-op view."""
    base = {key: value for key, value in row.items() if key != "presenterLayout"}
    if row["type"] != "presenter-layout-window":
        if row["presenterLayout"] is not None:
            raise RuntimeError("Only actual presenter operations may carry presenterLayout")
        return base
    payload = {key for key, value in row.items() if key not in ("type", "clauseIndex") and value is not None}
    if payload != _TIMED or len(proposal_trim(row["reason"])) < 8:
        raise RuntimeError("V8 presenter operation has mismatched payload or reason")
    index = integer(row["beatIndex"], "presenter beat index", 127)
    start = integer(row["startAnchor"], "presenter start anchor", 60001)
    end = integer(row["endAnchorExclusive"], "presenter end anchor", 60001)
    if index >= len(beats) or start >= end:
        raise RuntimeError("V8 presenter requires an existing beat and positive anchor window")
    beat = beats[index]
    if start < beat["startAnchor"] or end > beat["endAnchorExclusive"]:
        raise RuntimeError("V8 presenter window leaves its actual story beat")
    return {**base, "type": "preserve-cut", "reason": None, "beatIndex": None,
            "startAnchor": None, "endAnchorExclusive": None}


def parse_presenter_request(packet: dict) -> tuple[dict, dict]:
    """Keep actual V8 indices/clauses; prior_packet is only for old lane validators."""
    proposal = packet.get("proposal")
    if type(proposal) is not dict or type(proposal.get("schemaVersion")) is not int or proposal["schemaVersion"] != 8:
        raise RuntimeError("Presenter request requires the actual integer V8 proposal")
    try:
        validate_document(V8_SCHEMA, proposal)
    except OverflowError as error:
        raise RuntimeError("V8 proposal number exceeds finite representation") from error
    operations = [_layout_operation(row, proposal["beats"]) for row in proposal["operations"]]
    view = {**deepcopy(proposal), "schemaVersion": 7, "operations": deepcopy(operations)}
    local = {**deepcopy(packet), "proposal": view}
    _parse(local)  # Existing closed V7 schema/semantics and exact original raw UTF-16 coverage.
    evidence = packet.get("evidence")
    if type(evidence) is not dict or type(evidence.get("schemaVersion")) is not int or evidence["schemaVersion"] != 8:
        raise RuntimeError("Presenter requires exact actual V8 evidence")
    local["evidence"] = {**deepcopy(evidence), "schemaVersion": 7}
    return proposal, local


def _clock(evidence: dict) -> None:
    """Require canonical rational rate and complete bounded ordered anchors."""
    rate = evidence.get("frameRate")
    if type(rate) is not str or len(rate) > 64 or re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", rate) is None:
        raise RuntimeError("Presenter requires a canonical rational frame rate")
    numerator, denominator = (int(value) for value in rate.split("/"))
    if max(numerator, denominator) > 9007199254740991 or math.gcd(numerator, denominator) != 1:
        raise RuntimeError("Presenter frame rate must be reduced with safe components")
    total = integer(evidence.get("totalFrames"), "presenter total frames", 1_000_000_000)
    anchors = evidence.get("anchors")
    if not total or type(anchors) is not list or not 2 <= len(anchors) <= 60002:
        raise RuntimeError("Presenter requires a complete bounded program clock")
    checked = [integer(value, "presenter anchor", total) for value in anchors]
    if checked[0] != 0 or checked[-1] != total or any(a >= b for a, b in zip(checked, checked[1:])):
        raise RuntimeError("Presenter anchors must be a strictly ordered full-program range")


def _segments(evidence: dict) -> list[dict]:
    """Validate a contiguous retained source partition without inventing source timing."""
    rows, total = evidence.get("segments"), evidence["totalFrames"]
    if type(rows) is not list or not 1 <= len(rows) <= 60001:
        raise RuntimeError("Presenter requires bounded retained segments")
    anchors, cursor = set(evidence["anchors"]), 0
    for index, row in enumerate(rows):
        if type(row) is not dict or integer(row.get("index"), "segment index", 60000) != index:
            raise RuntimeError("Presenter segment indices differ from actual retained order")
        start = integer(row.get("startFrame"), "segment start", total)
        end = integer(row.get("endFrameExclusive"), "segment end", total)
        if start != cursor or end <= start or start not in anchors or end not in anchors:
            raise RuntimeError("Presenter segments must be a contiguous anchored partition")
        presenter_identifier(row.get("sourceId"))
        cursor = end
    if cursor != total:
        raise RuntimeError("Presenter retained segments do not cover the program")
    return rows


def _accepted(accepted: dict, evidence: dict, segments: list[dict]) -> None:
    """Retain the held target and actual ordered speed-one cut source identities."""
    if digest(accepted.get("target")) != digest(evidence.get("target")):
        raise RuntimeError("Presenter evidence target differs from accepted target")
    cuts = accepted.get("cutTrack")
    if type(cuts) is not list or len(cuts) != len(segments):
        raise RuntimeError("Presenter evidence lacks exact accepted cut coverage")
    for cut, segment in zip(cuts, segments):
        if type(cut) is not dict or cut.get("sourceId") != segment["sourceId"]:
            raise RuntimeError("Presenter accepted cut sources differ from retained segments")
        start, end = number(cut.get("start"), "cut start"), number(cut.get("end"), "cut end")
        if end <= start or number(cut.get("speed", 1), "cut speed") != 1:
            raise RuntimeError("Presenter requires the unchanged valid speed-one accepted cut")


def _window(row: dict, index: int, evidence: dict, canvas: PresenterCanvas) -> dict:
    """Bind one original operation to real anchors, source order and executable geometry."""
    anchors = evidence["anchors"]
    if row["endAnchorExclusive"] >= len(anchors):
        raise RuntimeError("Presenter operation references an absent actual anchor")
    start, end = anchors[row["startAnchor"]], anchors[row["endAnchorExclusive"]]
    layout = row["presenterLayout"]
    sources = list(dict.fromkeys(segment["sourceId"] for segment in evidence["segments"]
        if segment["endFrameExclusive"] > start and segment["startFrame"] < end))
    if not sources or sources != layout["sourceIds"]:
        raise RuntimeError("Presenter sourceIds differ from chronological retained occurrences")
    compile_presenter_geometry(layout, canvas, (start, end))
    return {"operationIndex": index, "startFrame": start, "endFrameExclusive": end, "layout": deepcopy(layout)}


def requested_presenter_windows(accepted: dict, proposal: dict, evidence: dict) -> list[dict]:
    """Sort disjoint windows without relabeling indices or granting media eligibility."""
    selected = [(index, row) for index, row in enumerate(proposal["operations"]) if row["type"] == "presenter-layout-window"]
    if not selected:
        return []
    if len(selected) > 32:
        raise RuntimeError("Presenter supports at most 32 explicit windows")
    _clock(evidence)
    _accepted(accepted, evidence, _segments(evidence))
    target = evidence["target"]
    canvas = PresenterCanvas(target.get("width"), target.get("height"), evidence["totalFrames"], "yuv420p")
    windows = [_window(row, index, evidence, canvas) for index, row in selected]
    windows.sort(key=lambda row: (row["startFrame"], row["operationIndex"]))
    if any(row["startFrame"] < prior["endFrameExclusive"] for prior, row in zip(windows, windows[1:])):
        raise RuntimeError("Presenter windows overlap; no last-writer-wins layout")
    return windows
