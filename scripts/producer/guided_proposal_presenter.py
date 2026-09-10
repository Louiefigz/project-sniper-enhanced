"""Pure actual V8 presenter intake; no source, media, rights or approval grant.

The owner must authenticate original documents, accepted operator context,
source-set entries and the original work clock. This module only rederives
request metadata and applies the existing narrower executable geometry policy.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass

from cut_preview_io import digest
from edit_scope import LANES, SCOPES, resolve_lanes
from graphics.presenter_layout_contract import integer, number, presenter_identifier
from guided_proposal_presenter_frames import parse_presenter_request, requested_presenter_windows
from guided_proposal_reframe import proposal_trim

PRESENTER_POLICY_SCOPE = "admitted-project-presentation-metadata-not-source-rights-or-quality-approval"
_COLLISIONS = ("presenterLayouts", "presenter", "overlays")


@dataclass(frozen=True)
class RequestedPresenterValidation:
    """Local validation result, never persisted or substituted for actual V8 evidence.

    prior_packet is only for existing V7 crop/music validators. Its nested values
    are separate copies; the caller must retain actual packet bytes for every
    hash, review, authority and execution record.
    """
    windows: tuple[dict, ...]
    prior_packet: dict


def _string(value: object, maximum: int) -> str:
    """Match TS code-point limits and opaque, nonblank text without normalization."""
    if type(value) is not str or not proposal_trim(value) or len(value) > maximum:
        raise RuntimeError("Presenter metadata requires bounded nonblank text")
    return value


def _sha(value: object) -> str:
    """Check byte-identity spelling, not the referenced bytes or source authority."""
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RuntimeError("Presenter metadata requires a canonical SHA256")
    return value


def _positive(value: object, maximum: int = 9007199254740991) -> int:
    """Reject booleans and unsafe/nonpositive integer metadata."""
    result = integer(value, "presenter positive metadata", maximum)
    if not result:
        raise RuntimeError("Presenter metadata must be positive")
    return result


def _lanes(accepted: dict) -> dict:
    """Use the actual explicit accepted scope and TS directive-only override class."""
    target = accepted.get("target")
    if type(target) is not dict or type(target.get("scope")) is not str or target["scope"] not in SCOPES:
        raise RuntimeError("Presenter requires an explicit accepted scope")
    lanes = target.get("lanes")
    lanes = {} if lanes is None else lanes
    if type(lanes) is not dict or any(key not in LANES or type(value) is not str
            or value not in ("auto", "off", "operator") for key, value in lanes.items()):
        raise RuntimeError("Presenter lane overrides require exact known directive words")
    return resolve_lanes({"scope": target["scope"], "lanes": lanes})


def _asset(row: object) -> dict:
    """Retain all admitted-row metadata without resolving paths or asserting rights."""
    if type(row) is not dict:
        raise RuntimeError("Presenter manifest asset must be an object")
    for key in ("originalPath", "path", "admissionReceiptPath"):
        _string(row.get(key), 4096)
    kind, duration = row.get("kind"), row.get("duration")
    if type(kind) is not str or kind not in ("image", "video"):
        raise RuntimeError("Presenter asset requires exact image/video kind")
    if kind == "image" and (duration is not None or "duration" not in row):
        raise RuntimeError("Presenter image requires explicit null duration")
    if kind == "video" and number(duration, "video duration") <= 0:
        raise RuntimeError("Presenter video requires positive finite duration")
    size = row.get("resolution")
    if type(size) is not list or len(size) != 2:
        raise RuntimeError("Presenter asset requires exact resolution metadata")
    return {"assetId": presenter_identifier(row.get("id")), "sourceSha256": _sha(row.get("sourceSha256")),
        "sourceSizeBytes": _positive(row.get("sourceSizeBytes")), "admissionReceiptSha256": _sha(row.get("admissionReceiptSha256")),
        "kind": kind, "durationS": duration, "width": _positive(size[0], 16384),
        "height": _positive(size[1], 16384), "rights": "unverified"}


def guided_presenter_policy(accepted: dict, manifest: dict) -> dict:
    """Reconstruct every bounded ordered asset, never discard invalid unused rows."""
    lanes, rows = _lanes(accepted), manifest.get("broll", [])
    if type(rows) is not list or len(rows) > 128:
        raise RuntimeError("Presenter catalog requires at most 128 assets")
    assets = [_asset(row) for row in rows]
    if len({row["assetId"] for row in assets}) != len(assets):
        raise RuntimeError("Presenter asset IDs are ambiguous")
    return {"schemaVersion": 1, "scope": PRESENTER_POLICY_SCOPE,
        "acceptedMotionEnabled": lanes["motion"] == "auto", "acceptedBrollEnabled": lanes["broll"] == "auto", "assets": assets}


def _unchanged(accepted: dict, candidate: dict, keys: tuple[str, ...]) -> None:
    """Keep field presence distinct from explicit null and preserve exact values."""
    for key in keys:
        if (key in accepted) != (key in candidate) or digest(accepted.get(key)) != digest(candidate.get(key)):
            raise RuntimeError(f"Candidate {key} differs from inherited presenter/cut authority")


def _target(accepted: dict, candidate: dict, proposal: dict) -> None:
    """Allow only unchanged target or the full builder's exact paired decoration."""
    target, actual = accepted.get("target"), candidate.get("target")
    if type(target) is not dict or type(actual) is not dict:
        raise RuntimeError("Presenter accepted/candidate target must be an object")
    decorated = {**target, "graphicsStyle": proposal["graphicsStyle"], "graphicsStyleRationale": proposal["graphicsStyleRationale"]}
    if digest(actual) not in (digest(target), digest(decorated)):
        raise RuntimeError("Candidate target differs from accepted and exact proposal style pair")


def _selection(accepted: dict, windows: list[dict], policy: dict) -> None:
    """Require activated lanes, fresh layout authority and the exact selected asset."""
    if not policy["acceptedMotionEnabled"] or not policy["acceptedBrollEnabled"] or any(key in accepted for key in _COLLISIONS):
        raise RuntimeError("Presenter requires motion/broll auto and absent inherited layout/overlays")
    assets = {row["assetId"]: row for row in policy["assets"]}
    for window in windows:
        layout = window["layout"]
        asset = assets.get(layout["assetId"])
        if asset is None:
            raise RuntimeError("Requested presenter asset is absent from the exact catalog")
        if asset["kind"] == "image" and layout["assetStart"]["numerator"] != 0:
            raise RuntimeError("Presenter still image requires exact assetStart 0/1")


def validate_requested_presenter(accepted: dict, candidate: dict, packet: dict,
                                 manifest: dict) -> RequestedPresenterValidation | None:
    """Validate actual V8 then provide a LOCAL V7 view; historical versions stay closed."""
    if any(type(row) is not dict for row in (accepted, candidate, packet, manifest)):
        raise RuntimeError("Presenter intake requires four actual JSON objects")
    proposal = packet.get("proposal")
    version = proposal.get("schemaVersion") if type(proposal) is dict else None
    if type(version) is not int or version not in range(2, 9):
        raise RuntimeError("Presenter requires a supported integer proposal schema2..8")
    if version != 8:
        _unchanged(accepted, candidate, ("presenterLayouts",))
        return None
    proposal, local = parse_presenter_request(packet)
    policy, evidence = guided_presenter_policy(accepted, manifest), packet["evidence"]
    if digest(evidence.get("presenterPolicy")) != digest(policy):
        raise RuntimeError("V8 presenter policy differs from exact accepted target/manifest metadata")
    _target(accepted, candidate, proposal)
    _unchanged(accepted, candidate, ("presenter", "overlays", "cutTrack", "cutDecisions"))
    windows = requested_presenter_windows(accepted, proposal, evidence)
    if not windows:
        _unchanged(accepted, candidate, ("presenterLayouts",))
        return RequestedPresenterValidation((), local)
    _selection(accepted, windows, policy)
    if "presenterLayouts" not in candidate or digest(candidate["presenterLayouts"]) != digest(windows):
        raise RuntimeError("Candidate presenterLayouts differs from the actual V8 requested windows")
    return RequestedPresenterValidation(tuple(deepcopy(windows)), local)
