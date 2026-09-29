"""Composition-signature repetition checks shared by style application lanes."""
from __future__ import annotations

from dataclasses import dataclass, field

INTENTIONAL = frozenset({"signature", "callback", "necessary-repeat"})
_SIGNATURE_FIELDS = ("anatomy", "configuration", "development")


@dataclass
class StyleHistory:
    """Bounded identities and structural signatures seen in timeline order."""

    identities: set[str] = field(default_factory=set)
    anatomies: set[str] = field(default_factory=set)
    signatures: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RepeatFacts:
    """Facts used to check one authored repeat-mode declaration."""

    repeated_identity: bool
    repeated_anatomy: bool
    repeated_signature: bool


def normalized_style_text(value: str) -> str:
    """Normalize authored prose only for exact signature comparison."""
    return " ".join(value.casefold().split())


def composition_signature(row: dict) -> tuple[str, str]:
    """Return normalized anatomy and the information-development signature."""
    anatomy = normalized_style_text(row["anatomy"])
    signature = "\0".join(normalized_style_text(row[key])
                           for key in _SIGNATURE_FIELDS)
    return anatomy, signature


def _facts(identity: str, anatomy: str, signature: str,
           history: StyleHistory) -> RepeatFacts:
    return RepeatFacts(identity in history.identities,
                       anatomy in history.anatomies,
                       signature in history.signatures)


def _invalid_repeat(mode: str, facts: RepeatFacts) -> bool:
    repeated_form = facts.repeated_identity or facts.repeated_anatomy
    intentional = mode in INTENTIONAL
    return ((facts.repeated_signature and not intentional)
            or (mode == "new" and repeated_form)
            or (intentional and not repeated_form)
            or (mode == "varied" and not repeated_form))


def repeat_error(identity: str, row: dict, history: StyleHistory) -> bool:
    """Record one use and report a repeat-mode or formula mismatch."""
    anatomy, signature = composition_signature(row)
    invalid = _invalid_repeat(
        row["repeatMode"], _facts(identity, anatomy, signature, history))
    history.identities.add(identity)
    history.anatomies.add(anatomy)
    history.signatures.add(signature)
    return invalid


def assert_style_variation(rows: list[tuple[str, dict]]) -> None:
    """Reject catalog-ID rotation that preserves a prior visual formula."""
    history = StyleHistory()
    ordered = sorted(rows, key=lambda item: item[1]["sceneIndex"])
    for identity, row in ordered:
        if repeat_error(identity, row, history):
            raise ValueError(
                "Native stage evidence: long style repeat mode differs from prior use")
