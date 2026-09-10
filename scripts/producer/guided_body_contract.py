"""Closed body-only invocation metadata; held hashes are supplied by its owner.

Parsing does not prove a journal, a human approval or a stopped process. The
foreground controller authenticates those facts before supplying this distinct
activation. Historical non-executable body admission remains non-executable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from guided_opening_inputs import closed, hash_value
from guided_media_profile import SHORT_BODY_PROFILE
from guided_caption_profile import CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE
from guided_body_source_color_replay import validate_body_source_color_replay

BODY_PROFILE = "held-source-float-own-screen-body-v1"
BODY_SCOPE = "private-body-candidate-not-approval"
REFERENCES = {"admissionClaim", "heldInput", "approvedSnapshot", "openingInput", "openingResult",
              "budgetAdmission", "budgetPrecommit"}
RUNTIME_KEYS = {"dockerPath", "dockerSha256", "dockerSocketPath", "dockerSocketDevice", "dockerSocketInode",
    "imageId", "userId", "imageApprovalPath", "imageApprovalSha256", "runtimeRepoRoot"}
INPUT_KEYS = {"schemaVersion", "kind", "scope", "profile", "requestId", "executionId", "references",
              "runtime", "selectedGraphicOrders"}
ACTIVATION_KEYS = {"schemaVersion", "kind", "scope", "requestId", "executionId", "admissionClaimHash",
    "beforeJournalHash", "inputPath", "inputSha256", "outputRoot", "clockHash", "generationStartedAt",
    "budgetAdmissionHash", "budgetPrecommitHash", "selectedGraphicOrders", "runtime", "createdAt"}


@dataclass(frozen=True)
class BodyInvocation:
    """Explicit owned CLI arguments, not paths recovered from a result directory."""

    input_path: Path
    input_sha256: str
    activation_path: Path
    activation_sha256: str


def body_path(value: object) -> Path:
    """Validate spelling without requiring a future output to exist yet."""
    if type(value) is not str or not 1 < len(value) <= 4096 or not value.startswith("/") \
            or "\\" in value or any(ord(char) < 32 for char in value) \
            or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise RuntimeError("body path is not a bounded canonical absolute path")
    return Path(value)


def body_timestamp(value: object) -> datetime:
    """Match the controller's exact UTC millisecond timestamp format."""
    if type(value) is not str or len(value) != 24 or not value.endswith("Z"):
        raise RuntimeError("body timestamp is malformed")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RuntimeError("body timestamp is malformed") from error
    if result.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise RuntimeError("body timestamp is not exact UTC milliseconds")
    return result


def _uuid(value: object) -> None:
    """Match the controller's canonical RFC-variant UUID versions one through eight."""
    if type(value) is not str:
        raise RuntimeError("body invocation UUID is malformed")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise RuntimeError("body invocation UUID is malformed") from error
    if str(parsed) != value or parsed.version not in range(1, 9):
        raise RuntimeError("body invocation requires a canonical version1-through8 UUID")


def body_orders(value: object) -> list[int]:
    """Body owns all exact candidate indices; the opening's eight limit is unchanged."""
    if type(value) is not list or len(value) > 128 \
            or any(type(item) is not int for item in value) or value != list(range(len(value))):
        raise RuntimeError("body graphic orders are not the complete bounded candidate order")
    return value


def parse_body_input(value: object) -> dict:
    """Historical body parser remains closed to newer geometry classes."""
    return _body_input_profile(value, BODY_PROFILE)


def parse_current_body_input(value: object) -> dict:
    """Dispatch only registered explicit classes before dependent file reads."""
    from guided_presenter_intake import is_presenter_body_profile

    version = value.get("schemaVersion") if type(value) is dict else None
    if type(version) is not int or version not in (1, 2):
        raise RuntimeError("body media input version is unsupported")
    row = closed(value, INPUT_KEYS | ({"sourceColorReplay"} if version == 2 else set()), "body media input")
    legacy = (BODY_PROFILE, SHORT_BODY_PROFILE, CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE)
    if type(row["profile"]) is not str or (row["profile"] not in legacy and not is_presenter_body_profile(row["profile"])):
        raise RuntimeError("body media input role/profile is unsupported")
    return _body_input_profile(row, row["profile"], version)


def _body_input_profile(value: object, profile: str, version: int = 1) -> dict:
    """Shared closed shape, never a profile upgrade or execution permission."""
    row = closed(value, INPUT_KEYS | ({"sourceColorReplay"} if version == 2 else set()), "body media input")
    expected = {"schemaVersion": version, "kind": "guided-body-media-input", "scope": BODY_SCOPE, "profile": profile}
    if any(type(row[key]) is not type(item) or row[key] != item for key, item in expected.items()):
        raise RuntimeError("body media input role/profile is unsupported")
    _uuid(row["requestId"])
    _uuid(row["executionId"])
    body_orders(row["selectedGraphicOrders"])
    closed(row["runtime"], RUNTIME_KEYS, "body runtime")
    refs = closed(row["references"], REFERENCES, "body input references")
    for name, reference in refs.items():
        closed(reference, {"path", "sha256"}, f"body {name} reference")
        body_path(reference["path"])
        hash_value(reference["sha256"])
    if version == 2:
        from copy import deepcopy
        return {**deepcopy(row), "sourceColorReplay": validate_body_source_color_replay(row["sourceColorReplay"])}
    return row


def parse_body_activation(value: object) -> dict:
    """No non-executable admission or mutually rehashed result can replace activation."""
    row = closed(value, ACTIVATION_KEYS, "body execution activation")
    expected = {"schemaVersion": 1, "kind": "guided-body-execution-activation",
                "scope": "private-body-owned-execution-not-approval"}
    if any(type(row[key]) is not type(item) or row[key] != item for key, item in expected.items()):
        raise RuntimeError("body execution activation role is unsupported")
    _uuid(row["requestId"])
    _uuid(row["executionId"])
    for key in ("admissionClaimHash", "beforeJournalHash", "inputSha256", "clockHash",
                "budgetAdmissionHash", "budgetPrecommitHash"):
        hash_value(row[key])
    for key in ("inputPath", "outputRoot"):
        body_path(row[key])
    if body_timestamp(row["createdAt"]) < body_timestamp(row["generationStartedAt"]):
        raise RuntimeError("body activation predates its original generation clock")
    body_orders(row["selectedGraphicOrders"])
    closed(row["runtime"], RUNTIME_KEYS, "body runtime")
    return row
