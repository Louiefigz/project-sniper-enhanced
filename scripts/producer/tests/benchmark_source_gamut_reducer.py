"""Synthetic-memory reducer timing, never decode, gamut or two-hour proof.

Run with the producer and TEST directories on PYTHONPATH and Python -B. Each
case feeds 384 MiB through the actual framed reducer, including its payload
hashes, supplied-frame joins and original deadline checks. There are no media
files, subprocesses, downloads or writes; only this JSON report goes to stdout.
The 64 MiB rotating ring is not claimed to exceed every machine's last cache.
"""
from __future__ import annotations

import json
import struct
import sys
import time
from typing import TYPE_CHECKING

_BEGAN = time.monotonic()
_DEADLINE = _BEGAN + 30
sys.dont_write_bytecode = True

from color.deadline import require_time, wall_budget

if TYPE_CHECKING:
    from _source_gamut_reducer_fixture import GamutFixture
    from color.source_gamut_reducer import FramedFloatReducer

_MIB = 1024 ** 2
_GEOMETRY = (512, 512)
_FRAMES = 128
_FRAME_BYTES = _GEOMETRY[0] * _GEOMETRY[1] * 12
_CASES = (("hot-64KiB", 64 * 1024, 1), ("hot-1MiB", _MIB, 1),
          ("rotating-64MiB-at-1MiB", _MIB, 64))
_FALSE_FLAGS = ("nativeExecutionProved", "gamutQualified", "transformApplicable",
                "gradeApplicable", "deliveryApproved")


def _rss_bytes() -> int | None:
    """Report process high-water RSS, not an instantaneous per-case allocation."""
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(value)
    if sys.platform.startswith("linux"):
        return int(value * 1024)
    return None


def _payloads(spec: tuple[str, int, int]) -> tuple[bytes, ...]:
    """Allocate immutable, exact float32 samples outside the measured feed loop."""
    _, size, count = spec
    if size > _MIB or _FRAME_BYTES % size or size % 4:
        raise ValueError("TEST benchmark chunk geometry changed")
    values = (0.5,) if count == 1 else tuple((index + 1) / 128 for index in range(count))
    return tuple(struct.pack("<f", value) * (size // 4) for value in values)


def _feed_frame(reducer: FramedFloatReducer, payloads: tuple[bytes, ...], row: dict) -> None:
    """Cycle existing byte objects without generating or copying timed payloads."""
    remaining = _FRAME_BYTES
    while remaining:
        chunk = payloads[row["pushCalls"] % len(payloads)]
        reducer.push(chunk)
        remaining -= len(chunk)
        row["acceptedPayloadBytes"] += len(chunk)
        row["pushCalls"] += 1


def _reduce(reducer: FramedFloatReducer, fixture: GamutFixture,
            payloads: tuple[bytes, ...], row: dict) -> dict:
    """Time the real frame-header, payload, SHA, record and terminal operations."""
    for index, frame in enumerate(fixture.frames):
        reducer.begin_frame(frame, fixture.header(index))
        _feed_frame(reducer, payloads, row)
        reducer.end_frame()
        row["completedFrames"] += 1
    return reducer.finish(fixture.original_terminal, fixture.measurement_terminal)


def _validate_result(result: dict, row: dict) -> None:
    """Require full synthetic coverage without promoting supplied records."""
    expected = _FRAMES * _FRAME_BYTES
    if result["payloadBytes"] != expected or row["acceptedPayloadBytes"] != expected \
            or result["frameCount"] != _FRAMES or result["sampleRangeValid"] is not True:
        raise RuntimeError("TEST benchmark did not finish its exact valid sample coverage")
    if any(result[key] is not False for key in _FALSE_FLAGS):
        raise RuntimeError("TEST benchmark result incorrectly implies native authority")
    row.update(originalRecordsSha256=result["originalRecordsSha256"],
               joinedRecordsSha256=result["joinedRecordsSha256"],
               sampleRangeValid=True, resultScope=result["scope"],
               resultFlags={key: result[key] for key in _FALSE_FLAGS})


def _case(spec: tuple[str, int, int], rows: list[dict], deadline: float) -> None:
    """Retain setup and failed/complete timing under the same aggregate cutoff."""
    from _source_gamut_reducer_fixture import gamut_fixture
    from color.source_gamut_reducer import FramedFloatReducer

    require_time(deadline)
    began = time.monotonic()
    row = {"case": spec[0], "status": "setup", "chunkBytes": spec[1],
           "residentPayloadBytes": spec[1] * spec[2], "acceptedPayloadBytes": 0,
           "pushCalls": 0, "completedFrames": 0, "rssHighWaterBeforeBytes": _rss_bytes()}
    rows.append(row)
    fixture, payloads = gamut_fixture(_FRAMES, _GEOMETRY), _payloads(spec)
    reducer = FramedFloatReducer(fixture.context, lambda: require_time(deadline))
    row["setupElapsedSeconds"] = time.monotonic() - began
    timed = time.monotonic()
    row["status"] = "running"
    try:
        result = _reduce(reducer, fixture, payloads, row)
        _validate_result(result, row)
        require_time(deadline)
        row["status"] = "complete"
    except Exception:
        row["status"] = "failed"
        raise
    finally:
        row["elapsedSeconds"] = time.monotonic() - timed
        row["rssHighWaterAfterBytes"] = _rss_bytes()
    row["bytesPerSecond"] = row["acceptedPayloadBytes"] / row["elapsedSeconds"]
    row["samplesPerSecond"] = row["bytesPerSecond"] / 4


def _execute(report: dict, deadline: float) -> None:
    """Measure imports separately, then three complete bounded fresh contexts."""
    began = time.monotonic()
    import numpy as np
    from _source_gamut_reducer_fixture import gamut_fixture

    if not callable(gamut_fixture):
        raise RuntimeError("TEST synthetic source-reference fixture is unavailable")
    report.update(numpyVersion=np.__version__, importSetupSeconds=time.monotonic() - began)
    for spec in _CASES:
        _case(spec, report["cases"], deadline)


def _projection(rows: list[dict]) -> dict:
    """Arithmetic extrapolation only; it omits transport, decode and transform."""
    pixels = 3840 * 2160 * 20_004
    size = pixels * 12
    return {"source": "C0679-retained-dimensions-arithmetic-no-source-read",
            "frames": 20_004, "pixelCount": pixels, "floatPayloadBytes": size,
            "minimumTransportBytesPerSecondFor1200Seconds": size / 1200,
            "reducerOnlySecondsAtMeasuredRates": {
                row["case"]: size / row["bytesPerSecond"] for row in rows
                if row["status"] == "complete"},
            "includesDecodeTransformPipeOrWholeWorkflow": False}


def main() -> None:
    """Print retained facts once; a timeout never becomes benchmark success."""
    report = {"schemaVersion": 1, "kind": "TEST-synthetic-framed-float-reducer-benchmark",
              "scope": "memory-reduction-hash-framing-not-native-or-two-hour-proof",
              "status": "running", "originalBudgetSeconds": 30,
              "pythonVersion": sys.version.split()[0], "geometry": list(_GEOMETRY),
              "framesPerCase": _FRAMES, "maximumPayloadBytesPerCase": _FRAMES * _FRAME_BYTES,
              "rssMeaning": "process-high-water-not-current-RSS-or-per-case-peak",
              "nativeExecutionProved": False, "gamutQualified": False,
              "transformApplicable": False, "deliveryApproved": False, "cases": []}
    failed = False
    try:
        with wall_budget(_DEADLINE):
            _execute(report, _DEADLINE)
            report["projection"] = _projection(report["cases"])
            report["status"] = "complete"
            report["totalElapsedSeconds"] = time.monotonic() - _BEGAN
            encoded = json.dumps(report, allow_nan=False, sort_keys=True)
            require_time(_DEADLINE)
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}",
                      totalElapsedSeconds=time.monotonic() - _BEGAN)
        encoded = json.dumps(report, allow_nan=False, sort_keys=True)
        failed = True
    print(encoded, flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
