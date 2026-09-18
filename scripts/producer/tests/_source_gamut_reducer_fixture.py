"""Small synthetic normalized records and float bytes; never native/media proof."""
from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable
from dataclasses import dataclass

from _grade_contract_fixture import terminal
from _grade_observation_v2_fixture import v2_context
from color.grade_frame_adapter import normalized_frame, observed_stream
from color.grade_observation_profile import V2_PROFILE
from color.grade_source_class import SourceFrameValidator
from color.source_gamut_reducer import FramedFloatReducer
from cross_runtime_canonical_json import canonical_compact_json


class GamutGuard:
    """A borrowed TEST-only guard whose deadline is never owned by the reducer."""

    def __init__(self) -> None:
        """Keep a small explicit TEST clock, with no system timer or work authority."""
        self.calls = 0
        self.now = 0
        self.end = 100
        self.callback: Callable[[], None] = lambda: None

    def __call__(self) -> None:
        """Check one original synthetic cutoff around a caller-controlled callback."""
        self.calls += 1
        self.callback()
        if self.now >= self.end:
            raise TimeoutError("TEST original observation deadline exhausted")


@dataclass
class GamutFixture:
    """Detached supplied data only; no filesystem, clock, decoder or source owner."""

    context: dict
    frames: list[dict]
    original_terminal: dict
    measurement_terminal: dict

    def header(self, index: int = 0) -> dict:
        """Explicit supplied measurement timestamps, not timestamps from byte count."""
        frame = self.frames[index]
        return {key: frame[key] for key in ("index", "pts", "durationTicks", "width", "height")} | {
            "timeBase": self.context["stream"]["timeBase"], "pixelFormat": "gbrpf32le",
            "payloadBytes": frame["width"] * frame["height"] * 12}

    def run(self, payloads: list[bytes], chunk_size: int = 7) -> dict:
        """Exercise the actual reducer in tiny split-float chunks with a TEST guard."""
        reducer = FramedFloatReducer(self.context, GamutGuard())
        for index, payload in enumerate(payloads):
            reducer.begin_frame(self.frames[index], self.header(index))
            for offset in range(0, len(payload), chunk_size):
                reducer.push(payload[offset:offset + chunk_size])
            reducer.end_frame()
        return reducer.finish(self.original_terminal, self.measurement_terminal)


def gamut_fixture(count: int = 1, size: tuple[int, int] = (2, 2)) -> GamutFixture:
    """Use actual unchanged V2 normalization/scanning on small synthetic geometry."""
    source, declaration, probe, rows = v2_context(count)
    probe["streams"][0].update(width=size[0], height=size[1])
    for row in rows:
        row.update(width=size[0], height=size[1])
    stream = observed_stream(probe, source, rows[0], V2_PROFILE)
    frames = [normalized_frame(row, index, V2_PROFILE) for index, row in enumerate(rows)]
    original = terminal(source)
    scanner = SourceFrameValidator(source, declaration, stream, V2_PROFILE)
    for frame in frames:
        scanner.add_frame(frame)
    records = scanner.finish(original)
    context = {"binding": source, "declaration": declaration, "stream": stream,
               "expectedRecordsSha256": records.records_sha256}
    measured = {"reachedEof": True, "exitCode": 0, "signal": None, "stderr": "",
                "stderrBytes": 0, "frames": count, "payloadBytes": count * size[0] * size[1] * 12}
    return GamutFixture(context, frames, original, measured)


def float_payload(values: tuple = (0.0, 0.25, 0.5, 1.0)) -> bytes:
    """Supply one 2x2 G/B/R frame without pretending these values were decoded."""
    return struct.pack("<12f", *(values * 3))


def joined_digest(fixture: GamutFixture, payloads: list[bytes]) -> str:
    """Independently spell the exact canonical metadata plus raw-payload transcript."""
    rows = [{"kind": "frame", "original": fixture.frames[index], "measurement": fixture.header(index),
             "payloadSha256": hashlib.sha256(payload).hexdigest()} for index, payload in enumerate(payloads)]
    rows.append({"kind": "terminal", "original": fixture.original_terminal,
                 "measurement": fixture.measurement_terminal})
    return hashlib.sha256("".join(canonical_compact_json(row) + "\n" for row in rows).encode()).hexdigest()


def frame_operation(reducer: FramedFloatReducer, records: tuple, stage: str) -> None:
    """Select the precise callback stage without skipping actual reducer work."""
    fixture, header = records
    if stage == "begin":
        reducer.begin_frame(fixture.frames[0], header)
    elif stage == "push":
        reducer.push(b"x")
    else:
        reducer.end_frame()


def wrong_order(reducer: FramedFloatReducer, fixture: GamutFixture, operation: str) -> None:
    """Exercise protocol refusal with the real unchanged scanner underneath."""
    if operation == "open-finish":
        reducer.finish(fixture.original_terminal, fixture.measurement_terminal)
        return
    reducer.push(float_payload())
    reducer.end_frame()
    if operation == "push":
        reducer.push(b"x")
    elif operation == "end":
        reducer.end_frame()
    else:
        reducer.begin_frame(fixture.frames[0], fixture.header())
