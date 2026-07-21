"""Typed, controller-applied repair for one qualified graphic accent token."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache

from .repair_diff import changed_pointers
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_EFFECT = "SECTION_MARKER_ACCENT_V1"


class RepairIntentError(RuntimeError):
    """A typed repair is malformed, stale, ambiguous, or outside policy."""


@dataclass(frozen=True)
class ParentRefV1:
    """Exact approved generation expected by one repair."""

    authority_id: str
    publication_seq: int
    generation_id: str
    commit_digest: str
    plan_digest: str


@dataclass(frozen=True)
class RepairIntentV1:
    """Closed one-pointer compare-and-swap repair request."""

    expected_parent: ParentRefV1
    request_id: str
    graphic_id: str
    expected_old: str
    value: str


@dataclass(frozen=True)
class AccentRepairPolicy:
    """Controller-owned finite color catalog for this effect class."""

    policy_id: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class RepairApplication:
    """Private candidate plus exact before/after and changed-pointer receipt."""

    plan_json: bytes
    before_digest: str
    after_digest: str
    changed_pointers: tuple[str, ...]
    graphic_id: str
    policy_id: str

    def decoded_plan(self) -> dict:
        """Return a disposable copy; the authoritative candidate stays immutable."""
        return json.loads(self.plan_json)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RepairIntentError("repair input is not canonical JSON") from exc
    return encoded.encode("ascii")


def approved_plan_digest(plan: dict) -> str:
    """Return the domain-separated identity of exact approved plan bytes."""
    if type(plan) is not dict:
        raise RepairIntentError("approved plan must be an object")
    return hashlib.sha256(b"sniper-approved-plan-v1\0" + _canonical(plan)).hexdigest()


def _canonical_uuid(label: str, value: object) -> str:
    if type(value) is not str:
        raise RepairIntentError(f"{label} must be a UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise RepairIntentError(f"{label} must be a UUID") from exc
    if parsed != value:
        raise RepairIntentError(f"{label} must use canonical UUID form")
    return parsed


def _parent(value: object) -> ParentRefV1:
    keys = {
        "authorityId",
        "commitDigest",
        "generationId",
        "planDigest",
        "publicationSeq",
    }
    valid = (
        type(value) is dict
        and set(value) == keys
        and type(value.get("authorityId")) is str
        and bool(_IDENTITY.fullmatch(value["authorityId"]))
        and type(value.get("publicationSeq")) is int
        and value["publicationSeq"] > 0
        and all(
            type(value.get(key)) is str and bool(_DIGEST.fullmatch(value[key]))
            for key in ("commitDigest", "planDigest")
        )
    )
    if not valid:
        raise RepairIntentError("expected parent is invalid")
    generation = _canonical_uuid("generation ID", value["generationId"])
    return ParentRefV1(
        value["authorityId"],
        value["publicationSeq"],
        generation,
        value["commitDigest"],
        value["planDigest"],
    )


def _color(label: str, value: object) -> str:
    if type(value) is not str or not _COLOR.fullmatch(value):
        raise RepairIntentError(f"{label} must be a six-digit hex token")
    return value.upper()


def parse_repair_intent(value: object) -> RepairIntentV1:
    """Parse the sole fast-path repair schema; reject unknown authority."""
    keys = {
        "effectClass",
        "expectedOld",
        "expectedParent",
        "op",
        "realizationKind",
        "relativePointer",
        "requestId",
        "schemaVersion",
        "target",
        "value",
    }
    target_keys = {"id", "lane"}
    valid = (
        type(value) is dict
        and set(value) == keys
        and type(value.get("schemaVersion")) is int
        and value["schemaVersion"] == 1
        and value["effectClass"] == _EFFECT
        and value["realizationKind"] == "deterministic-mp4"
        and value["op"] == "replace"
        and value["relativePointer"] == "/spec/accent"
        and type(value.get("target")) is dict
        and set(value["target"]) == target_keys
        and value["target"].get("lane") == "graphicsTrack"
        and type(value["target"].get("id")) is str
        and bool(_GRAPHIC_ID.fullmatch(value["target"]["id"]))
    )
    if not valid:
        raise RepairIntentError("repair intent envelope is invalid")
    request_id = _canonical_uuid("request ID", value["requestId"])
    old, new = _color("expected old value", value["expectedOld"]), _color(
        "replacement value", value["value"]
    )
    if old == new:
        raise RepairIntentError("repair intent is already satisfied")
    return RepairIntentV1(
        _parent(value["expectedParent"]), request_id, value["target"]["id"], old, new
    )


def accent_policy(values: tuple[str, ...]) -> AccentRepairPolicy:
    """Freeze a canonical controller-owned allowed-token catalog."""
    normalized = tuple(sorted({_color("policy value", value) for value in values}))
    if not normalized:
        raise RepairIntentError("accent repair policy must not be empty")
    encoded = _canonical(
        {"allowedValues": normalized, "effectClass": _EFFECT, "schemaVersion": 1}
    )
    policy_id = hashlib.sha256(
        b"sniper-accent-repair-policy-v1\0" + encoded
    ).hexdigest()
    return AccentRepairPolicy(policy_id, normalized)


@lru_cache(maxsize=1)
def current_accent_policy() -> AccentRepairPolicy:
    """Build the effect-specific policy from named repository brand tokens."""
    import brand

    tokens = brand.load_tokens()
    try:
        values = tuple(tokens[name] for name in ("accent", "gold"))
    except KeyError as exc:
        raise RepairIntentError("section-marker accent tokens are missing") from exc
    return accent_policy(values)


def _validate_policy(policy: AccentRepairPolicy) -> None:
    current = current_accent_policy()
    if type(policy) is not AccentRepairPolicy or not same_wire_value(policy, current):
        raise RepairIntentError("accent repair policy identity is invalid")


def validate_parent_ref(value: object) -> None:
    """Require the exact canonical five-field approved-generation reference."""
    if type(value) is not ParentRefV1:
        raise RepairIntentError("approved parent reference is invalid")
    document = {
        "authorityId": value.authority_id,
        "publicationSeq": value.publication_seq,
        "generationId": value.generation_id,
        "commitDigest": value.commit_digest,
        "planDigest": value.plan_digest,
    }
    if not same_wire_value(value, _parent(document)):
        raise RepairIntentError("approved parent reference is invalid")


def _validate_intent(value: object) -> None:
    if type(value) is not RepairIntentV1:
        raise RepairIntentError("repair intent instance is invalid")
    validate_parent_ref(value.expected_parent)
    valid = (
        _canonical_uuid("request ID", value.request_id) == value.request_id
        and bool(_GRAPHIC_ID.fullmatch(value.graphic_id))
        and _color("expected old value", value.expected_old) == value.expected_old
        and _color("replacement value", value.value) == value.value
        and value.expected_old != value.value
    )
    if not valid:
        raise RepairIntentError("repair intent instance is invalid")


def _target(plan: dict, graphic_id: str) -> tuple[list, int, dict]:
    track = plan.get("graphicsTrack")
    if not isinstance(track, list) or not track:
        raise RepairIntentError("approved plan has no graphics track")
    ids = []
    for row in track:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise RepairIntentError("graphics track has no stable identity")
        if not _GRAPHIC_ID.fullmatch(row["id"]):
            raise RepairIntentError("graphics track identity is not canonical")
        ids.append(row["id"])
    if len(set(ids)) != len(ids):
        raise RepairIntentError("graphics track identities are ambiguous")
    if graphic_id not in ids:
        raise RepairIntentError("repair target is absent")
    index = ids.index(graphic_id)
    return track, index, track[index]


def apply_repair(
    intent: RepairIntentV1,
    actual_parent: ParentRefV1,
    plan: dict,
    policy: AccentRepairPolicy,
) -> RepairApplication:
    """Apply exactly one stable-ID accent CAS to a private canonical copy."""
    _validate_intent(intent)
    validate_parent_ref(actual_parent)
    if actual_parent != intent.expected_parent:
        raise RepairIntentError("approved parent is stale")
    _validate_policy(policy)
    frozen = json.loads(_canonical(plan))
    before = approved_plan_digest(frozen)
    if before != actual_parent.plan_digest:
        raise RepairIntentError("approved plan digest does not match parent")
    track, index, row = _target(frozen, intent.graphic_id)
    if row.get("kind") != "section-marker" or not isinstance(row.get("spec"), dict):
        raise RepairIntentError("repair target is not a section marker")
    actual = _color("current accent", row["spec"].get("accent"))
    if actual != intent.expected_old:
        raise RepairIntentError("repair expected old value is stale")
    if intent.value not in policy.allowed_values:
        raise RepairIntentError("repair value is outside accent policy")
    track[index]["spec"]["accent"] = intent.value
    changed = changed_pointers(plan, frozen)
    expected = (f"/graphicsTrack/{index}/spec/accent",)
    if changed != expected:
        raise RepairIntentError("repair widened beyond its registered pointer")
    after = approved_plan_digest(frozen)
    return RepairApplication(
        _canonical(frozen), before, after, changed, intent.graphic_id, policy.policy_id
    )
