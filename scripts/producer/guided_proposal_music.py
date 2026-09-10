"""Exact requested music projection; metadata never grants source/rights approval.

The caller retains original document/clock authority and runs the existing real
source-set gate. This module does no file discovery, decoding, mixing or consent.
"""
from __future__ import annotations

import math
import re
import sys
from copy import deepcopy

from cut_preview_io import digest
from guided_proposal_reframe import _parse, proposal_trim

MUSIC_SCOPE = "admitted-project-music-metadata-not-source-rights-or-quality-approval"
_MAX_SAFE_INTEGER = 9007199254740991


def _text(value: object) -> str:
    """Match the TS opaque ID contract without trimming or normalizing identity."""
    if type(value) is not str or not proposal_trim(value) or len(value) > 128:
        raise RuntimeError("music assetId requires nonempty text of at most 128 code points")
    return value


def _sha(value: object) -> str:
    """Require canonical byte identities, never a caller-selected path digest."""
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RuntimeError("music admission/source identity is not a SHA256")
    return value


def _positive(value: object, integer: bool = False) -> int | float:
    """Match JS finite numbers and safe integer metadata without boolean coercion."""
    if type(value) not in (int, float) or not 0 < value <= sys.float_info.max or not math.isfinite(value):
        raise RuntimeError("music catalog requires positive finite admitted size/duration")
    if integer and (value > _MAX_SAFE_INTEGER or value != int(value)):
        raise RuntimeError("music catalog byte count requires a positive safe integer")
    return int(value) if integer else value


def _asset(row: dict) -> dict:
    """Project exact admitted row metadata; the source-set reader proves its paths."""
    if any(type(row.get(key)) is not str or not row[key]
           for key in ("originalPath", "path", "admissionReceiptPath")):
        raise RuntimeError("music catalog lacks complete admitted project references")
    return {"assetId": _text(row.get("id")), "sourceSha256": _sha(row.get("sourceSha256")),
        "sourceSizeBytes": _positive(row.get("sourceSizeBytes"), True),
        "admissionReceiptSha256": _sha(row.get("admissionReceiptSha256")),
        "durationS": _positive(row.get("duration")), "rights": "unverified"}


def _music_enabled(accepted: dict) -> bool:
    """Read mirrored metadata only; the TS owner must bind its original ctx intent."""
    target = accepted.get("target")
    if type(target) is not dict:
        raise RuntimeError("accepted music target is not an object")
    if "music" in target and type(target["music"]) is not bool:
        raise RuntimeError("accepted target.music must be an actual boolean when present")
    return target.get("music", False)


def guided_music_policy(accepted: dict, manifest: dict) -> dict:
    """Reconstruct all bounded ordered metadata, including excluded builtin count."""
    enabled, rows = _music_enabled(accepted), manifest.get("music")
    rows = [] if rows is None else rows
    if type(rows) is not list or len(rows) > 128:
        raise RuntimeError("music catalog exceeds its 128-row metadata contract")
    ids, assets, excluded = set(), [], 0
    for row in rows:
        if type(row) is not dict or _text(row.get("id")) in ids:
            raise RuntimeError("music catalog has malformed or ambiguous asset IDs")
        ids.add(row["id"])
        if row.get("source") == "builtin" and row.get("originalPath") is None:
            excluded += 1
            continue
        assets.append(_asset(row))
    return {"schemaVersion": 1, "scope": MUSIC_SCOPE, "acceptedMusicEnabled": enabled,
        "gapDb": {"minimum": 3, "maximum": 40}, "duck": True,
        "fitting": "full-program-loop-crossfade-and-ending-fade", "assets": assets,
        "excludedBuiltinCount": excluded}


def _unchanged(accepted: dict, candidate: dict) -> None:
    """Even null/disabled additions or removals change the inherited music authority."""
    if ("music" in accepted) != ("music" in candidate) or digest(accepted.get("music")) != digest(candidate.get("music")):
        raise RuntimeError("candidate music differs from unchanged inherited music authority")


def validate_requested_music(accepted: dict, candidate: dict, packet: dict, manifest: dict) -> dict | None:
    """Bind actual7 request and policy; all other/no-op requests preserve music exactly."""
    proposal = packet.get("proposal")
    version = proposal.get("schemaVersion") if type(proposal) is dict else None
    if type(version) is not int or version not in (2, 3, 4, 5, 6, 7):
        raise RuntimeError("music authority requires a supported actual integer proposal schema2..7")
    if version != 7:
        _unchanged(accepted, candidate)
        return None
    proposal = _parse(packet)
    policy = guided_music_policy(accepted, manifest)
    evidence = packet.get("evidence")
    if type(evidence) is not dict or type(evidence.get("schemaVersion")) is not int \
            or evidence["schemaVersion"] != 7 or digest(evidence.get("musicPolicy")) != digest(policy):
        raise RuntimeError("V7 music policy differs from exact accepted target and manifest metadata")
    operations = [row for row in proposal["operations"] if row["type"] == "music-bed-full-program"]
    if not operations:
        _unchanged(accepted, candidate)
        return None
    if not policy["acceptedMusicEnabled"] or "music" in accepted:
        raise RuntimeError("requested music requires accepted target.music:true and absent inherited music")
    selection = operations[0]["music"]
    if selection["assetId"] not in {row["assetId"] for row in policy["assets"]}:
        raise RuntimeError("requested music is absent from the exact admitted-project catalog")
    expected = {"enabled": True, "assetId": selection["assetId"], "gapDb": selection["gapDb"], "duck": True}
    if "music" not in candidate or digest(candidate["music"]) != digest(expected):
        raise RuntimeError("candidate music differs from actual requested music projection")
    return deepcopy(next(row for row in manifest["music"] if row["id"] == selection["assetId"]))


def verify_music_admission(selection: dict | None, entries: list[dict]) -> None:
    """Join selected metadata to the already verified exact music-lane source entry."""
    if selection is None:
        return
    expected = {"lane": "music", "mediaKind": "timed-media", "originalPath": selection["originalPath"],
        "snapshotPath": selection["path"], "sha256": selection["sourceSha256"],
        "sizeBytes": selection["sourceSizeBytes"], "admissionReceiptPath": selection["admissionReceiptPath"],
        "admissionReceiptSha256": selection["admissionReceiptSha256"]}
    matches = [row for row in entries if row.get("originalPath") == selection["originalPath"]]
    if len(matches) != 1 or digest(matches[0]) != digest(expected):
        raise RuntimeError("selected music differs from actual verified source-set lane/path/bytes/receipt")
