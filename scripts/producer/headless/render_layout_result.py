"""Closed validation of actual written-frame CSS observations, never approval."""
from __future__ import annotations

import hashlib
import re
from fractions import Fraction

from headless.render_layout_contract import (
    CLI_SHA256, OBSERVER_FILES, PIPELINE_POLICY, SCOPE, canonical, closed,
    finite_number, sha, validate_request,
)


def _issues(value: object) -> list[str]:
    """Retain unsupported/unmeasured facts instead of normalizing them away."""
    if type(value) is not list or len(value) > 64 \
            or any(type(item) is not str or not 0 < len(item) <= 128 for item in value) \
            or value != sorted(set(value)):
        raise ValueError("layout issue inventory is malformed")
    return value


def _inventory(value: object, profile: str) -> list[dict]:
    """Validate the bounded actual DOM text/role inventory."""
    pipeline = profile == PIPELINE_POLICY
    bounds = (3, 16) if pipeline else (4, 12)
    pattern = (r"eyebrow|explainer|footnote|headline-line-[12]|node-[1-6]|connector-[1-5]"
               if pipeline else r"eyebrow|title|title-accent|step-[1-5]-(marker|title|subtitle)")
    if type(value) is not list or not bounds[0] <= len(value) <= bounds[1]:
        raise ValueError("layout DOM role inventory is incomplete")
    for row in value:
        closed(row, {"id", "text"}, "layout role")
        if type(row["id"]) is not str or not re.fullmatch(pattern, row["id"]) \
                or type(row["text"]) is not str \
                or len(row["id"]) > 64 or len(row["text"]) > 4096:
            raise ValueError("layout role identity/text is malformed")
        nonlexical = row["id"].startswith("connector-") if pipeline else row["id"] == "title-accent"
        if not nonlexical and not row["text"].strip():
            raise ValueError("layout required lexical role has no text")
    ids = [row["id"] for row in value]
    required = {"node-1", "node-2", "connector-1"} if pipeline else {"title", "title-accent"}
    if ids != sorted(set(ids)) or not required.issubset(ids):
        raise ValueError("layout role inventory is unordered or incomplete")
    return value


def _role(value: object, expected: dict) -> bool:
    """Check measured visibility/envelope and honest unsupported paint status."""
    row = closed(value, {"id", "text", "bounds", "opacity", "issues"}, "layout frame role")
    if {key: row[key] for key in ("id", "text")} != expected:
        raise ValueError("layout actual role/text changed across frames")
    opacity = finite_number(row["opacity"])
    if not 0 <= opacity <= 1:
        raise ValueError("layout role opacity is out of bounds")
    issues = _issues(row["issues"])
    bounds = row["bounds"]
    if bounds is None:
        if opacity > 0 and "visible-role-has-no-bounds" not in issues:
            raise ValueError("layout visible role has unreported missing bounds")
        return False
    if opacity <= 0 or type(bounds) is not list or len(bounds) != 4:
        raise ValueError("layout role geometry conflicts with visibility")
    x0, y0, x1, y1 = [finite_number(item) for item in bounds]
    if not x0 < x1 or not y0 < y1 or max(abs(item) for item in bounds) > 1000000:
        raise ValueError("layout role envelope is malformed")
    if (x0 < 0 or y0 < 0 or x1 > 1920 or y1 > 1080) and "role-outside-canvas" not in issues:
        raise ValueError("layout out-of-frame role was reported as supported")
    return True


def _frame(value: object, context: tuple) -> set[str]:
    """Every acknowledged output frame retains exact rational seek identity."""
    index, rate, inventory = context
    row = closed(value, {"frameIndex", "timeNumerator", "timeDenominator", "captureSha256", "roles", "issues"}, "layout frame")
    if type(row["frameIndex"]) is not int or row["frameIndex"] != index \
            or row["timeNumerator"] != str(index * rate.denominator) \
            or row["timeDenominator"] != str(rate.numerator):
        raise ValueError("layout actual frame clock/order differs")
    sha(row["captureSha256"])
    _issues(row["issues"])
    if type(row["roles"]) is not list or len(row["roles"]) != len(inventory):
        raise ValueError("layout frame omitted actual DOM roles")
    return {expected["id"] for role, expected in zip(row["roles"], inventory)
            if _role(role, expected)}


def _file_rows(value: object) -> list[dict]:
    """Require the exact observer source closure, not arbitrary expected shapes."""
    if type(value) is not list or len(value) != len(OBSERVER_FILES):
        raise ValueError("layout observer implementation closure is incomplete")
    for row in value:
        closed(row, {"path", "sha256", "sizeBytes"}, "layout observer source")
        sha(row["sha256"])
        if type(row["sizeBytes"]) is not int or not 0 < row["sizeBytes"] <= 65536:
            raise ValueError("layout observer source size is malformed")
    paths = [row["path"] for row in value]
    if paths != [f"/opt/sniper-motion/container/{name}" for name in OBSERVER_FILES]:
        raise ValueError("layout observer implementation closure is incomplete")
    return value


def validate_observation(value: object, request: dict, expected: dict) -> dict:
    """Compare to caller-held request/media/code, never a self-sealed claim.

    ``expected`` is the actual owned media hash/size and approved image's
    independently held observer source list. This function is structural; the
    live process/runtime/readback adapter must supply those observations.
    """
    validate_request(request)
    row = closed(value, {"schemaVersion", "kind", "policy", "scope", "request", "requestSha256", "cliSha256", "observerSources", "media", "frames", "roleInventory", "framesObserved", "status"}, "layout observation")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["kind"] != "sealed-animation-layout-observation" \
            or row["policy"] != request["profile"] or row["scope"] != SCOPE:
        raise ValueError("layout observation version/scope differs")
    if canonical(row["request"]) != canonical(request) or row["requestSha256"] != hashlib.sha256(canonical(request)).hexdigest():
        raise ValueError("layout observation request differs from actual held request")
    if row["cliSha256"] != CLI_SHA256 or row["observerSources"] != expected["observerSources"] or row["media"] != expected["media"]:
        raise ValueError("layout observation actual media/implementation differs")
    _file_rows(row["observerSources"])
    closed(row["media"], {"sha256", "sizeBytes"}, "layout media")
    sha(row["media"]["sha256"])
    if type(row["media"]["sizeBytes"]) is not int or not 0 < row["media"]["sizeBytes"] <= 512 * 1024 * 1024:
        raise ValueError("layout media size is malformed")
    inventory = _inventory(row["roleInventory"], request["profile"])
    if inventory != expected["roleInventory"]:
        raise ValueError("layout role/text inventory differs from exact captured native spec")
    frames = row["frames"]
    if type(frames) is not list or len(frames) != request["totalFrames"] \
            or type(row["framesObserved"]) is not int or row["framesObserved"] != len(frames):
        raise ValueError("layout observation lacks whole written-frame coverage")
    visible = set().union(*[_frame(frame, (index, Fraction(request["frameRate"]), inventory)) for index, frame in enumerate(frames)])
    clean = visible == {item["id"] for item in inventory} and all(
        not frame["issues"] and all(not role["issues"] for role in frame["roles"]) for frame in frames)
    if row["status"] != ("observed" if clean else "unqualified"):
        raise ValueError("layout observation status suppresses unqualified geometry")
    return row
