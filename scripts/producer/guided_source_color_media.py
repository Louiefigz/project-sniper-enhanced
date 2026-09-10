"""Opt-in source-color worker composition under the ORIGINAL opening deadline.

No source-color flag may silently enter the legacy route. Parsing is lexical
and performs no filesystem/native work. Actual staging, source observation and
base preparation retain their existing owners and budgets; this module never
acquires/releases leases or grants color, creative or delivery approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from weakref import WeakKeyDictionary

from guided_opening_claim import HeldOpeningClaim
from guided_opening_inputs import OpeningInputs, hash_value
from guided_opening_lifetime import OpeningSourceLifetime
from guided_opening_prepare import OpeningPreparation, prepare_source_color_full_program
from guided_source_color_base import hold_bt709_base_identity
from guided_source_color_base_context import SourceColorBaseContext, assert_source_color_plan
from guided_source_color_opening import (
    SourceColorOpeningAuthority, SourceColorOpeningContext, observe_opening_source_colors,
)


_INVOCATIONS = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class SourceColorMediaInvocation:
    """Explicit original server transport, not source-observation or cleanup authority."""

    input_path: Path
    input_sha256: str
    producer_dir: Path
    resource_dir: Path

    def __post_init__(self) -> None:
        """Keep transport fields as originally supplied, before any worker callback."""
        _INVOCATIONS[self] = _invocation_fields(self)


def _path(value: object) -> Path:
    """Reject normalization of supplied path spelling before any filesystem work."""
    if type(value) is not str or not value.startswith("/") or len(value) > 4096 \
            or "\\" in value or any(ord(char) < 32 for char in value) \
            or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise ValueError("source-color media invocation requires exact absolute paths")
    return Path(value)


def parse_source_color_media_invocation(values: tuple) -> SourceColorMediaInvocation | None:
    """Require all four explicit flags or none; never discover a sidecar or infer a declaration."""
    if type(values) is not tuple or len(values) != 4:
        raise ValueError("source-color media invocation requires exactly four optional fields")
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("all four source-color media flags must be supplied together")
    location, sha256, producer, resource = values
    return SourceColorMediaInvocation(_path(location), hash_value(sha256), _path(producer), _path(resource))


def validate_source_color_media_invocation(value: SourceColorMediaInvocation | None) -> None:
    """Validate direct Python calls before even the private output-directory check."""
    if value is None:
        return
    if _invocation_fields(value) != _INVOCATIONS.get(value):
        raise RuntimeError("source-color original invocation transport changed")


def _invocation_fields(value: SourceColorMediaInvocation) -> tuple:
    """Validate typed path/hash fields without constructing replacement invocation authority."""
    if type(value) is not SourceColorMediaInvocation or set(vars(value)) != {
            "input_path", "input_sha256", "producer_dir", "resource_dir"}:
        raise ValueError("source-color media invocation is not the exact optional transport")
    paths = (value.input_path, value.producer_dir, value.resource_dir)
    if any(type(path) is not type(Path()) for path in paths):
        raise ValueError("source-color media invocation path types differ")
    for path in paths:
        _path(str(path))
    hash_value(value.input_sha256)
    return tuple((id(path), str(path)) for path in paths), value.input_sha256


def _guard(lifetime: OpeningSourceLifetime, invocation: SourceColorMediaInvocation) -> Callable[[], None]:
    """Capture one original source guard and retain original transport around its callbacks."""
    original = lifetime.guard

    def check() -> None:
        """Never adopt invocation fields changed by setup, source or publication work."""
        validate_source_color_media_invocation(invocation)
        original()
        validate_source_color_media_invocation(invocation)

    return check


def prepare_source_color_media(inputs: OpeningInputs, claim: HeldOpeningClaim, execution: tuple,
                               invocation: SourceColorMediaInvocation) -> tuple[OpeningPreparation, SourceColorBaseContext]:
    """Compose actual source observations and base consumption with one captured guard."""
    validate_source_color_media_invocation(invocation)
    if invocation is None:
        raise ValueError("source-color preparation requires the explicit four-field invocation")
    assert_source_color_plan(inputs)
    root, clock, pipeline = execution
    lifetime = clock.phase("source-color-original-lifetime", lambda: OpeningSourceLifetime(inputs, claim, pipeline, clock))
    validate_source_color_media_invocation(invocation)
    guard = _guard(lifetime, invocation)
    authority = SourceColorOpeningAuthority(invocation.producer_dir, invocation.resource_dir, guard)
    opening = SourceColorOpeningContext(inputs, claim, clock, authority)
    # The adapter protects mandatory cleanup itself and explicitly refuses a nested phase alarm.
    batch = observe_opening_source_colors((invocation.input_path, invocation.input_sha256), opening)
    identity = clock.phase("source-color-bt709-identity", lambda: hold_bt709_base_identity(batch))
    context = SourceColorBaseContext(inputs, clock, identity, guard)
    prepared = clock.phase("ordinary-full-program-preparation", lambda: prepare_source_color_full_program(inputs, root, context))
    SourceColorBaseContext.assert_current(context)
    validate_source_color_media_invocation(invocation)
    return prepared, context
