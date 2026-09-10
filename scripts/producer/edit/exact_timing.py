"""Exact rational frame/sample timing for P2 cut repair.

Seconds are accepted only as compatibility input.  Authority is carried as
canonical positive rationals, half-open integer frame ranges, and half-open
integer sample ranges.  The formulas mirror the normative command-driven
editing contract without replacing ``compile_timeline``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Mapping

_DECIMAL_TOKEN = re.compile(
    r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


class TimingContractError(ValueError):
    """A timing value cannot enter exact P2 authority."""


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, str):
        raise TimingContractError(f"{label} must be a positive integer string")
    text = value
    if not text.isdigit() or text.startswith("0"):
        raise TimingContractError(f"{label} must be a canonical positive integer string")
    number = int(text)
    if number <= 0:
        raise TimingContractError(f"{label} must be positive")
    return number


@dataclass(frozen=True)
class PositiveRational:
    """A reduced positive fraction serialized as canonical integer strings."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if type(self.numerator) is not int or type(self.denominator) is not int:
            raise TimingContractError("positive rational terms must be integers")
        if self.numerator <= 0 or self.denominator <= 0:
            raise TimingContractError("positive rational terms must be positive")
        if math.gcd(self.numerator, self.denominator) != 1:
            raise TimingContractError("positive rational must be reduced")

    @classmethod
    def from_value(cls, value: object) -> "PositiveRational":
        """Parse a canonical object, integer, or raw decimal JSON token."""
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            if set(value) != {"numerator", "denominator"}:
                raise TimingContractError("positive rational has unknown or missing fields")
            numerator = _positive_integer(value["numerator"], "numerator")
            denominator = _positive_integer(value["denominator"], "denominator")
            divisor = math.gcd(numerator, denominator)
            if divisor != 1:
                raise TimingContractError("positive rational object is not reduced")
            return cls(numerator, denominator)
        if isinstance(value, bool) or isinstance(value, float):
            raise TimingContractError("binary floating point cannot enter timing authority")
        if isinstance(value, int):
            if value <= 0:
                raise TimingContractError("positive rational must be positive")
            return cls(value, 1)
        return cls.from_decimal_token(value)

    @classmethod
    def from_decimal_token(cls, value: object) -> "PositiveRational":
        """Reduce one raw finite positive decimal/exponent token exactly."""
        if not isinstance(value, str) or not _DECIMAL_TOKEN.fullmatch(value):
            raise TimingContractError("decimal timing token is not a JSON number")
        try:
            decimal = Decimal(value)
        except InvalidOperation as exc:
            raise TimingContractError("decimal timing token is invalid") from exc
        if not decimal.is_finite() or decimal <= 0:
            raise TimingContractError("decimal timing token must be finite and positive")
        numerator, denominator = decimal.as_integer_ratio()
        divisor = math.gcd(numerator, denominator)
        return cls(numerator // divisor, denominator // divisor)

    @property
    def fraction(self) -> Fraction:
        """Return the exact standard-library fraction."""
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, str]:
        """Return the schema-authoritative representation."""
        return {
            "numerator": str(self.numerator),
            "denominator": str(self.denominator),
        }


@dataclass(frozen=True)
class FrameRange:
    """Half-open delivery-frame range."""

    start_frame: int
    end_frame_exclusive: int

    def __post_init__(self) -> None:
        if type(self.start_frame) is not int \
                or type(self.end_frame_exclusive) is not int \
                or self.start_frame < 0 \
                or self.end_frame_exclusive <= self.start_frame:
            raise TimingContractError("frame range must be non-empty and non-negative")

    @property
    def length(self) -> int:
        """Number of delivery frames."""
        return self.end_frame_exclusive - self.start_frame

    def to_dict(self) -> dict[str, int]:
        """Return schema field names."""
        return {
            "startFrame": self.start_frame,
            "endFrameExclusive": self.end_frame_exclusive,
        }


@dataclass(frozen=True)
class SampleRange:
    """Half-open integer sample range."""

    start_sample: int
    end_sample_exclusive: int

    def __post_init__(self) -> None:
        if type(self.start_sample) is not int \
                or type(self.end_sample_exclusive) is not int \
                or self.start_sample < 0 \
                or self.end_sample_exclusive <= self.start_sample:
            raise TimingContractError("sample range must be non-empty and non-negative")

    @property
    def length(self) -> int:
        """Number of samples."""
        return self.end_sample_exclusive - self.start_sample

    def to_dict(self) -> dict[str, int]:
        """Return schema field names."""
        return {
            "startSample": self.start_sample,
            "endSampleExclusive": self.end_sample_exclusive,
        }


@dataclass(frozen=True)
class ProjectClock:
    """Exact delivery FPS and project audio sample clock."""

    fps: PositiveRational
    sample_rate: int

    def __post_init__(self) -> None:
        if type(self.sample_rate) is not int or self.sample_rate <= 0:
            raise TimingContractError("project sample rate must be positive")

    def sample_at_frame(self, frame: int) -> int:
        """Return ``B(frame) = floor(frame × S × q / p)``."""
        if type(frame) is not int or frame < 0:
            raise TimingContractError("frame must be non-negative")
        p, q = self.fps.numerator, self.fps.denominator
        return frame * self.sample_rate * q // p

    def samples_for_frames(self, frames: FrameRange) -> SampleRange:
        """Partition one frame range on the single absolute sample clock."""
        return SampleRange(
            self.sample_at_frame(frames.start_frame),
            self.sample_at_frame(frames.end_frame_exclusive),
        )

    def normalize_source_sample(self, sample: int, source_rate: int) -> int:
        """Return ``P(sample) = floor(sample × S / source_rate)``."""
        if type(sample) is not int or type(source_rate) is not int \
                or sample < 0 or source_rate <= 0:
            raise TimingContractError("source sample/rate is invalid")
        return sample * self.sample_rate // source_rate

    def containing_frame(self, sample: int) -> int:
        """Map a project sample to its containing delivery frame with floor."""
        if type(sample) is not int or sample < 0:
            raise TimingContractError("sample must be non-negative")
        p, q = self.fps.numerator, self.fps.denominator
        upper = Fraction((sample + 1) * p, self.sample_rate * q)
        return max(0, ceil_fraction(upper) - 1)


def ceil_fraction(value: Fraction) -> int:
    """Return the mathematical ceiling of a non-negative fraction."""
    if value < 0:
        raise TimingContractError("cannot ceil a negative timing value")
    return (value.numerator + value.denominator - 1) // value.denominator


def source_span_frames(
    samples: int,
    source_rate: int,
    speed: PositiveRational,
    clock: ProjectClock,
) -> int:
    """Conservatively quantize a source span so complete speech is retained."""
    if type(samples) is not int or type(source_rate) is not int \
            or samples <= 0 or source_rate <= 0:
        raise TimingContractError("source span/rate must be positive")
    duration = Fraction(samples, source_rate) / speed.fraction
    return ceil_fraction(duration * clock.fps.fraction)


def source_span_project_samples(
    samples: int,
    source_rate: int,
    speed: PositiveRational,
    clock: ProjectClock,
) -> int:
    """Conservatively map a source handle onto the absolute project clock."""
    if type(samples) is not int or type(source_rate) is not int \
            or samples <= 0 or source_rate <= 0:
        raise TimingContractError("source span/rate must be positive")
    duration = Fraction(samples, source_rate) / speed.fraction
    return ceil_fraction(duration * clock.sample_rate)


@dataclass(frozen=True)
class SourceRetime:
    """Exact source-sample to project-sample map for one resolved segment."""

    source_samples: SampleRange
    output_frames: FrameRange
    source_rate: int
    clock: ProjectClock

    def __post_init__(self) -> None:
        if type(self.source_rate) is not int or self.source_rate <= 0:
            raise TimingContractError("source retime rate must be a positive integer")

    def normalized_source_samples(self) -> SampleRange:
        """Return the exact shared-boundary ``P`` projection."""
        return SampleRange(
            self.clock.normalize_source_sample(
                self.source_samples.start_sample, self.source_rate),
            self.clock.normalize_source_sample(
                self.source_samples.end_sample_exclusive, self.source_rate),
        )

    def output_sample_for_source(self, source_sample: int) -> int:
        """Apply the absolute normative ``R(n)`` mapping."""
        if not self.source_samples.start_sample <= source_sample <= \
                self.source_samples.end_sample_exclusive:
            raise TimingContractError("source sample is outside the retimed segment")
        normalized = self.normalized_source_samples()
        normalized_point = self.clock.normalize_source_sample(
            source_sample, self.source_rate)
        output = self.clock.samples_for_frames(self.output_frames)
        offset = normalized_point - normalized.start_sample
        return output.start_sample + offset * output.length // (
            normalized.length)

    def receipt(
        self,
        requested_speed: PositiveRational,
        max_speed_deviation: PositiveRational,
    ) -> dict[str, object]:
        """Bind requested and effective retime ranges without float drift."""
        output = self.clock.samples_for_frames(self.output_frames)
        normalized = self.normalized_source_samples()
        effective = Fraction(normalized.length, output.length)
        deviation = abs(effective - requested_speed.fraction)
        if deviation > max_speed_deviation.fraction:
            raise TimingContractError(
                "effective retime exceeds the frozen speed-deviation tolerance")
        return {
            "requestedSpeed": requested_speed.to_dict(),
            "maxAbsoluteSpeedDeviation": max_speed_deviation.to_dict(),
            "sourceSampleRange": self.source_samples.to_dict(),
            "normalizedSourceSampleRange": normalized.to_dict(),
            "outputFrameRange": self.output_frames.to_dict(),
            "outputSampleRange": output.to_dict(),
            "sourceSampleRate": self.source_rate,
            "projectSampleRate": self.clock.sample_rate,
            "effectiveRatio": PositiveRational(
                effective.numerator, effective.denominator).to_dict(),
        }
