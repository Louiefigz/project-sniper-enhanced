"""Strict leaf values shared by the approved-parent wire parser."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass

from . import artifact_contract as ac
from . import quality_pass_contract as qc

ArtifactRefV1 = ac.ArtifactRefV1
MediaFactsV1 = ac.MediaFactsV1
MediaRefV1 = ac.MediaRefV1
GraphicAssetRefV1 = qc.GraphicAssetRefV1

_ARTIFACT_KEYS = frozenset("path sha256 sizeBytes".split())
_MEDIA_KEYS = frozenset("artifact facts".split())
_FACT_ORDER = (
    "width height durationSeconds fpsNumerator fpsDenominator frameCount "
    "sizeBytes videoCodec pixelFormat profile alphaMode audioCodec"
)
_FACT_KEYS = frozenset(_FACT_ORDER.split())
_GRAPHIC_KEYS = frozenset(
    "graphicId media receipt renderArtifactDigest renderBuildDigest "
    "renderIntentDigest".split()
)
_CRITIC_KEYS = frozenset("artifact lens".split())
_LENSES = ("composition", "editorial")


class ApprovedParentSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class CriticArtifactRefV1:
    lens: str
    artifact: ArtifactRefV1


def parse_artifact(value: object) -> ArtifactRefV1:
    """Parse one exact generation-relative immutable file reference."""
    if type(value) is not dict or set(value) != _ARTIFACT_KEYS:
        raise ApprovedParentSchemaError("artifact reference keys are invalid")
    parsed = ArtifactRefV1(
        value.get("path"), value.get("sha256"), value.get("sizeBytes")
    )
    try:
        ac.validate_artifact_ref(parsed)
    except ac.ArtifactContractError as exc:
        raise ApprovedParentSchemaError(str(exc)) from exc
    return parsed


def parse_media(value: object) -> MediaRefV1:
    """Parse exact media bytes and facts measured from those bytes."""
    if type(value) is not dict or set(value) != _MEDIA_KEYS:
        raise ApprovedParentSchemaError("media reference keys are invalid")
    facts = value.get("facts")
    if type(facts) is not dict or set(facts) != _FACT_KEYS:
        raise ApprovedParentSchemaError("media facts keys are invalid")
    parsed = MediaRefV1(
        parse_artifact(value["artifact"]),
        MediaFactsV1(*(facts[key] for key in _FACT_ORDER.split())),
    )
    try:
        ac.validate_media_ref(parsed)
    except ac.ArtifactContractError as exc:
        raise ApprovedParentSchemaError(str(exc)) from exc
    return parsed


def _parse_graphic(value: object) -> GraphicAssetRefV1:
    if type(value) is not dict or set(value) != _GRAPHIC_KEYS:
        raise ApprovedParentSchemaError("graphic reference keys are invalid")
    parsed = GraphicAssetRefV1(
        value.get("graphicId"),
        value.get("renderIntentDigest"),
        parse_media(value.get("media")),
        parse_artifact(value.get("receipt")),
        value.get("renderArtifactDigest"),
        value.get("renderBuildDigest"),
    )
    try:
        qc.validate_graphic_asset(parsed)
    except qc.QualityPassContractError as exc:
        raise ApprovedParentSchemaError(str(exc)) from exc
    return parsed


def parse_graphics(value: object) -> tuple[GraphicAssetRefV1, ...]:
    """Preserve an exact nonempty graphic order with unique stable IDs."""
    if type(value) is not list or not value:
        raise ApprovedParentSchemaError("assets must be a nonempty ordered array")
    parsed = tuple(_parse_graphic(row) for row in value)
    identities = tuple(asset.graphic_id for asset in parsed)
    if len(identities) != len(set(identities)):
        raise ApprovedParentSchemaError("graphic identities are duplicated")
    return parsed


def parse_critics(value: object) -> tuple[CriticArtifactRefV1, ...]:
    """Require composition then editorial, each with its own artifact ref."""
    if type(value) is not list or len(value) != 2:
        raise ApprovedParentSchemaError("exactly two critic entries are required")
    if any(type(row) is not dict or set(row) != _CRITIC_KEYS for row in value):
        raise ApprovedParentSchemaError("critic entry keys are invalid")
    parsed = tuple(
        CriticArtifactRefV1(row["lens"], parse_artifact(row["artifact"]))
        for row in value
    )
    if tuple(item.lens for item in parsed) != _LENSES:
        raise ApprovedParentSchemaError("critic lens order is invalid")
    if parsed[0].artifact == parsed[1].artifact:
        raise ApprovedParentSchemaError("critic artifact refs must be distinct")
    return parsed


def artifact_refs(value: object) -> tuple[ArtifactRefV1, ...]:
    """Collect every immutable file reference from a parsed nested card."""
    if type(value) is ArtifactRefV1:
        return (value,)
    if type(value) is MediaRefV1:
        return (value.artifact,)
    if type(value) is GraphicAssetRefV1:
        return (value.media.artifact, value.receipt)
    if type(value) is tuple:
        return tuple(ref for item in value for ref in artifact_refs(item))
    if is_dataclass(value):
        return tuple(
            ref
            for field in fields(value)
            for ref in artifact_refs(getattr(value, field.name))
        )
    return ()
