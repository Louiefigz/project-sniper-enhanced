"""Incremental supplied-float record validation, not authenticated native gamut.

Each original normalized V2 frame is joined to an explicit measured header and
the SHA256 of exactly its G/B/R planar little-endian float32 payload. The joined
digest covers newline-delimited canonical {kind,original,measurement,...} frame
rows (with payloadSha256), then one terminal row. No timestamps are inferred
from byte counts. A future native producer must authenticate this correspondence.
The original borrowed guard bounds every operation; no allowance is created here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from typing import TypeVar

from color.grade_contract import closed
from color.grade_observation_profile import V2_PROFILE
from color.grade_source_class import SourceFrameValidator, SourceRecordValidation
from color.source_gamut_result import RESULT_KIND, RESULT_SCOPE, validate_gamut_reduction
from color.source_gamut_samples import MAX_CHUNK_BYTES, PlanarSamples, empty_channels
from color.source_picture_transform_contract import sha256
from cross_runtime_canonical_json import canonical_compact_json

_T = TypeVar("_T")
_CONTEXT = {"binding", "declaration", "stream", "expectedRecordsSha256"}
_HEADER = {"index", "pts", "durationTicks", "timeBase", "width", "height",
           "pixelFormat", "payloadBytes"}
_TERMINAL = {"reachedEof", "exitCode", "signal", "stderr", "stderrBytes", "frames", "payloadBytes"}


def _signature(value: object) -> str:
    """Preserve JSON numeric types when checking original caller-owned metadata."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class FramedFloatReducer:
    """Single-use, fail-sticky framed reducer; unknown history stays observable."""

    def __init__(self, context: object, guard: Callable[[], None]) -> None:
        """Capture original supplied metadata and guard before the first callback."""
        self._state = "open"
        self._original = context
        self._context = copy.deepcopy(closed(context, _CONTEXT, "gamut reduction context"))
        self._fixed = _signature(self._context)
        self._guard = guard
        self._original_guard = guard
        if not callable(guard):
            raise ValueError("gamut reducer needs its original callable guard")
        sha256(self._context["expectedRecordsSha256"])
        self._scanner = SourceFrameValidator(self._context["binding"], self._context["declaration"],
                                            self._context["stream"], V2_PROFILE)
        self._pixels = self._context["stream"]["width"] * self._context["stream"]["height"]
        self._channels = empty_channels()
        self._joined = hashlib.sha256()
        self._count = 0
        self._bytes = 0
        self._active: tuple | None = None
        self._run(lambda records: None)

    def _metadata(self, records: tuple, fixed: tuple) -> None:
        """Check retained context/current frame and all newly supplied metadata."""
        if self._state != "busy" or _signature(self._original) != self._fixed \
                or _signature(self._context) != self._fixed:
            raise ValueError("gamut reducer original context or operation changed")
        if any(_signature(original) != _signature(snapshot)
               for original, snapshot in zip(records, fixed)):
            raise ValueError("gamut reducer original operation metadata changed")
        if self._active is not None:
            original, held, _, _ = self._active
            if any(_signature(row) != _signature(saved) for row, saved in zip(original, held)):
                raise ValueError("gamut reducer original frame metadata changed")

    def _check(self, records: tuple, fixed: tuple, guard: Callable[[], None]) -> None:
        """Call only the captured original guard and reject swallowed reentry."""
        self._metadata(records, fixed)
        if self._guard is not guard:
            raise ValueError("gamut reducer original guard changed")
        guard()
        self._metadata(records, fixed)
        if self._guard is not guard:
            raise ValueError("gamut reducer original guard changed")

    def _run(self, action: Callable[[tuple], _T], records: tuple = ()) -> _T:
        """Capture arguments before callbacks and permanently poison any failed call."""
        if self._state != "open":
            self._state = "failed"
            raise ValueError("gamut reducer failed, finished or reentered")
        self._state = "busy"
        guard = self._original_guard
        try:
            fixed = copy.deepcopy(records)
            self._check(records, fixed, guard)
            result = action(fixed)
            returned = copy.deepcopy(result)
            self._check(records, fixed, guard)
            if _signature(result) != _signature(returned):
                raise ValueError("gamut reducer result changed during its final guard")
        except BaseException:
            self._state = "failed"
            raise
        self._state = "open"
        return returned

    def begin_frame(self, original_frame: object, measured_header: object) -> None:
        """Join exact original PTS/geometry to supplied measurement before bytes."""
        records = (original_frame, measured_header)
        self._run(lambda fixed: self._begin(records, fixed), records)

    def _begin(self, records: tuple, fixed: tuple) -> None:
        """Validate unchanged V2 records, then create one bounded planar counter."""
        if self._active is not None:
            raise ValueError("gamut frame is already open")
        original, header = fixed
        self._scanner.add_frame(original)
        row = closed(header, _HEADER, "gamut measured frame header")
        expected = {key: original[key] for key in ("index", "pts", "durationTicks", "width", "height")}
        expected.update(timeBase=self._context["stream"]["timeBase"],
                        pixelFormat="gbrpf32le", payloadBytes=self._pixels * 12)
        if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()):
            raise ValueError("gamut measured frame differs from original clock or geometry")
        self._active = (records, fixed, PlanarSamples(self._pixels, self._channels), hashlib.sha256())

    def push(self, chunk: bytes) -> None:
        """Accept 1..1MiB immutable bytes, including split floats/plane boundaries."""
        self._run(lambda records: self._push(chunk))

    def _push(self, chunk: bytes) -> None:
        """Hash exactly the supplied bytes only after bounded payload admission."""
        if self._active is None:
            raise ValueError("gamut payload has no open frame")
        if type(chunk) is not bytes or not 1 <= len(chunk) <= MAX_CHUNK_BYTES:
            raise ValueError("gamut payload needs immutable bytes within the chunk bound")
        self._active[2].push(chunk)
        self._active[3].update(chunk)

    def end_frame(self) -> None:
        """Finish exact planes and bind their raw digest to both metadata records."""
        records = self._active[0] if self._active is not None else ()
        self._run(lambda fixed: self._end(), records)

    def _end(self) -> None:
        """Keep only aggregate counters and the ordered digest after this frame."""
        if self._active is None:
            raise ValueError("gamut end has no open frame")
        _, (original, measurement), samples, payload = self._active
        samples.finish()
        self._join({"kind": "frame", "original": original, "measurement": measurement,
                    "payloadSha256": payload.hexdigest()})
        self._count += 1
        self._bytes += samples.bytes
        self._active = None

    def _join(self, row: dict) -> None:
        """Bind exact supplied metadata/payload order with canonical newline framing."""
        self._joined.update((canonical_compact_json(row) + "\n").encode("utf8"))

    def finish(self, original_terminal: object, measurement_terminal: object) -> dict:
        """Require two independent clean EOFs and the expected original digest."""
        result = self._run(self._finish, (original_terminal, measurement_terminal))
        self._state = "finished"
        return result

    def _finish(self, records: tuple) -> dict:
        """Validate the closed result as data only; never promote its false scope."""
        if self._active is not None:
            raise ValueError("gamut stream has an unfinished frame")
        original, measurement = records
        row = closed(measurement, _TERMINAL, "gamut measurement terminal")
        expected = {"reachedEof": True, "exitCode": 0, "signal": None, "stderr": "",
                    "stderrBytes": 0, "frames": self._count, "payloadBytes": self._bytes}
        if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()):
            raise ValueError("gamut measurement did not finish cleanly at exact EOF")
        validated = self._scanner.finish(original)
        if validated.records_sha256 != self._context["expectedRecordsSha256"]:
            raise ValueError("gamut original record digest differs from expected records")
        self._join({"kind": "terminal", "original": original, "measurement": measurement})
        return validate_gamut_reduction(self._result(validated), validated)

    def _result(self, validated: SourceRecordValidation) -> dict:
        """Report supplied float counts while keeping every native/approval flag false."""
        valid = all(row["finiteCount"] == self._count * self._pixels
                    and row["belowZeroCount"] == row["aboveOneCount"] == 0
                    for row in self._channels.values())
        return {"schemaVersion": 1, "kind": RESULT_KIND, "scope": RESULT_SCOPE,
                "binding": copy.deepcopy(self._context["binding"]),
                "originalRecordsSha256": validated.records_sha256,
                "joinedRecordsSha256": self._joined.hexdigest(), "frameCount": self._count,
                "pixelCount": self._count * self._pixels, "payloadBytes": self._bytes,
                "channels": self._channels, "sampleRangeValid": valid,
                "nativeExecutionProved": False, "gamutQualified": False,
                "transformApplicable": False, "gradeApplicable": False, "deliveryApproved": False}
