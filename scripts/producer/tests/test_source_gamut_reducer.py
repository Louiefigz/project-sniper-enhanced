"""Synthetic framed-byte adversarial checks; no decoder, media or source IO."""
from __future__ import annotations

import json
import struct
import unittest
from unittest.mock import patch

import numpy as np

from _source_gamut_reducer_fixture import (
    GamutGuard, float_payload, frame_operation, gamut_fixture, joined_digest, wrong_order,
)
from color import source_gamut_reducer as module, source_gamut_samples as samples
from color.source_gamut_reducer import FramedFloatReducer
from color.source_gamut_samples import MAX_CHUNK_BYTES


class SourceGamutReducerTests(unittest.TestCase):
    """Every supplied frame/float is counted; data validation remains a false scope."""

    def test_unknown_history_and_chunk_partitions_preserve_exact_join(self) -> None:
        """One-byte and cross-plane chunks bind the same original ordered transcript."""
        fixture = gamut_fixture(2)
        payloads = [float_payload(), float_payload((1, 0.5, 0.25, -0.0))]
        expected = fixture.run(payloads, 1)
        for size in (3, 4, 7, 15, 17, 48):
            self.assertEqual(fixture.run(payloads, size), expected)
        self.assertEqual(expected["joinedRecordsSha256"], joined_digest(fixture, payloads))
        self.assertEqual(expected["originalRecordsSha256"], fixture.context["expectedRecordsSha256"])
        self.assertEqual((expected["frameCount"], expected["pixelCount"], expected["payloadBytes"]), (2, 8, 96))
        self.assertEqual(fixture.context["declaration"]["historyState"], "unknown")
        for key in ("nativeExecutionProved", "gamutQualified", "transformApplicable",
                    "gradeApplicable", "deliveryApproved"):
            self.assertIs(expected[key], False)

    def test_planar_channels_nonfinite_and_exact_float32_extrema(self) -> None:
        """Physical G/B/R planes are not treated as interleaved RGB triplets."""
        tiny = struct.unpack("<f", struct.pack("<I", 1))[0]
        above = struct.unpack("<f", struct.pack("<I", 0x3f800001))[0]
        largest = float(np.finfo(np.float32).max)
        values = (0, 0.25, 0.5, 1, float("nan"), float("inf"), -float("inf"), 0.5,
                  -tiny, above, -largest, largest)
        result = gamut_fixture().run([struct.pack("<12f", *values)], 5)
        green, blue, red = (result["channels"][key] for key in ("g", "b", "r"))
        self.assertEqual((green["finiteCount"], green["minimum"], green["maximum"]), (4, 0, 1))
        self.assertEqual([blue[key] for key in ("finiteCount", "nanCount", "positiveInfinityCount",
                         "negativeInfinityCount", "minimum", "maximum")], [1, 1, 1, 1, 0.5, 0.5])
        self.assertEqual((red["belowZeroCount"], red["aboveOneCount"]), (2, 2))
        self.assertEqual((red["minimum"], red["maximum"]), (-largest, largest))
        self.assertFalse(result["sampleRangeValid"])

    def test_all_nonfinite_has_null_extrema_and_signed_zero_is_valid(self) -> None:
        """Nonfinite values are observed, not silently clipped or turned into extrema."""
        result = gamut_fixture().run([float_payload((float("nan"), float("inf"), -float("inf"), float("nan")))])
        for channel in result["channels"].values():
            self.assertEqual((channel["finiteCount"], channel["minimum"], channel["maximum"]), (0, None, None))
        self.assertTrue(gamut_fixture().run([float_payload((-0.0, 0.0, 1.0, -0.0))])["sampleRangeValid"])

    def test_maximum_chunk_and_carry_remain_bounded_without_frame_buffer(self) -> None:
        """A three-MiB synthetic frame crosses float/plane edges in bounded views."""
        fixture, guard = gamut_fixture(size=(512, 512)), GamutGuard()
        reducer = FramedFloatReducer(fixture.context, guard)
        reducer.begin_frame(fixture.frames[0], fixture.header())
        chunk = struct.pack("<f", 0.5) * (MAX_CHUNK_BYTES // 4)
        original, lengths = np.frombuffer, []
        def observed(data: bytes, **kwargs: object) -> np.ndarray:
            """Observe only reducer temporary bytes, without changing numeric work."""
            lengths.append(len(data))
            return original(data, **kwargs)
        with patch("color.source_gamut_samples.np.frombuffer", side_effect=observed):
            reducer.push(chunk[:3])
            for _ in range(2):
                reducer.push(chunk)
            reducer.push(chunk[3:])
        reducer.end_frame()
        self.assertTrue(reducer.finish(fixture.original_terminal, fixture.measurement_terminal)["sampleRangeValid"])
        self.assertLessEqual(max(lengths), MAX_CHUNK_BYTES + 3)

    def test_measured_headers_are_closed_exact_typed_clock_and_geometry(self) -> None:
        """Byte length cannot substitute for original PTS/duration or native dimensions."""
        changes = [("index", True), ("pts", 900001), ("durationTicks", 1000),
                   ("timeBase", "2/60000"), ("width", 2.0), ("height", 4),
                   ("pixelFormat", "rgb24"), ("payloadBytes", 47), ("extra", None)]
        for key, value in changes:
            fixture = gamut_fixture()
            header = fixture.header() | {key: value}
            reducer = FramedFloatReducer(fixture.context, GamutGuard())
            with self.subTest(key=key), self.assertRaises(ValueError):
                reducer.begin_frame(fixture.frames[0], header)
            self._failed(reducer, fixture)

    def test_original_source_cadence_and_metadata_are_not_relabelled(self) -> None:
        """The existing V2 source scanner still refuses duplicate/mixed original frames."""
        for key, value in (("index", 1), ("pts", 0), ("transfer", "bt709"),
                           ("width", 4), ("durationTicks", True), ("chromaLocation", "center")):
            fixture = gamut_fixture()
            reducer = FramedFloatReducer(fixture.context, GamutGuard())
            fixture.frames[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                reducer.begin_frame(fixture.frames[0], fixture.header())

    def test_payload_type_size_truncation_and_extra_bytes_poison(self) -> None:
        """Mutable views, empty chunks, oversize chunks and rounded partial floats refuse."""
        for chunk in (bytearray(4), memoryview(b"1234"), b"", b"x" * (MAX_CHUNK_BYTES + 1), b"x" * 49):
            fixture, reducer = self._started()
            with self.assertRaises(ValueError):
                reducer.push(chunk)
            self._failed(reducer, fixture)
        for size in (0, 1, 4, 47):
            fixture, reducer = self._started()
            if size:
                reducer.push(float_payload()[:size])
            with self.assertRaisesRegex(ValueError, "truncated"):
                reducer.end_frame()
            self._failed(reducer, fixture)

    def test_protocol_order_and_missing_or_extra_frames_cannot_finish(self) -> None:
        """A frame needs a header, complete payload and end before the next frame/EOF."""
        for operation in ("push", "end", "extra", "open-finish"):
            fixture, reducer = self._started()
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                wrong_order(reducer, fixture, operation)
            self._failed(reducer, fixture)

    def test_both_original_and_measurement_terminals_are_strict(self) -> None:
        """Neither one successful stream nor coercible counts imply two clean EOFs."""
        changes = [("reachedEof", 1), ("exitCode", False), ("signal", "SIGTERM"),
                   ("stderr", "warning"), ("stderrBytes", 0.0), ("frames", True),
                   ("payloadBytes", 49), ("extra", None)]
        for key, value in changes:
            fixture, reducer = self._completed()
            fixture.measurement_terminal[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                reducer.finish(fixture.original_terminal, fixture.measurement_terminal)
        for key, value in (("reachedEof", False), ("decoderExitCode", True), ("decoderWarningCount", 1)):
            fixture, reducer = self._completed()
            fixture.original_terminal[key] = value
            with self.assertRaises(ValueError):
                reducer.finish(fixture.original_terminal, fixture.measurement_terminal)

    def test_expected_original_digest_is_not_reconstructed_from_payload_size(self) -> None:
        """The caller's original complete normalized record digest remains indispensable."""
        fixture = gamut_fixture()
        fixture.context["expectedRecordsSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            fixture.run([float_payload()])

    def test_original_context_captured_before_first_guard_and_retained_later(self) -> None:
        """An arbitrary guard cannot establish a replacement metadata baseline."""
        fixture, guard = gamut_fixture(), GamutGuard()
        guard.callback = lambda: fixture.context["binding"].update(sourceSha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "context"):
            FramedFloatReducer(fixture.context, guard)
        fixture, reducer = self._started()
        fixture.context["stream"]["firstPts"] += 1
        with self.assertRaisesRegex(ValueError, "context"):
            reducer.push(float_payload())

    def test_frame_metadata_captured_before_first_and_last_end_callback(self) -> None:
        """Closing the active frame must not drop its original final callback hold."""
        for stage in ("begin", "push", "end"):
            fixture, guard = gamut_fixture(), GamutGuard()
            reducer, header = FramedFloatReducer(fixture.context, guard), fixture.header()
            if stage != "begin":
                reducer.begin_frame(fixture.frames[0], header)
                reducer.push(float_payload())
            at = guard.calls + (2 if stage == "end" else 1)
            guard.callback = lambda: header.update(pts=0) if guard.calls == at else None
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "metadata"):
                frame_operation(reducer, (fixture, header), stage)
            self._failed(reducer, fixture)

    def test_terminal_capture_and_guard_identity_survive_callbacks(self) -> None:
        """Original EOFs and callable identity cannot be swapped between operations."""
        fixture, guard = gamut_fixture(), GamutGuard()
        reducer = FramedFloatReducer(fixture.context, guard)
        reducer._guard = lambda: None
        with self.assertRaisesRegex(ValueError, "guard changed"):
            reducer.begin_frame(fixture.frames[0], fixture.header())
        fixture, reducer = self._completed()
        reducer._original_guard.callback = lambda: fixture.measurement_terminal.update(frames=2)
        with self.assertRaisesRegex(ValueError, "metadata"):
            reducer.finish(fixture.original_terminal, fixture.measurement_terminal)

    def test_original_deadline_failure_and_swallowed_reentry_stay_failed(self) -> None:
        """No retry, fresh allowance or swallowed inner exception resets this consumer."""
        fixture, reducer = self._started()
        guard = reducer._original_guard
        guard.now = guard.end
        with self.assertRaises(TimeoutError):
            reducer.push(float_payload())
        guard.now = 0
        self._failed(reducer, fixture)
        fixture, reducer = self._started()
        def reenter() -> None:
            """Swallow the inner exception; the outer operation must still refuse."""
            with self.assertRaises(ValueError):
                reducer.end_frame()
        reducer._original_guard.callback = reenter
        with self.assertRaises(ValueError):
            reducer.push(float_payload())
        self._failed(reducer, fixture)

    def test_returned_result_cannot_mutate_during_final_guard_or_alias_later(self) -> None:
        """A validator leaf's mutable return cannot escape the final original guard."""
        fixture, reducer = self._completed()
        published, validate = [], module.validate_gamut_reduction
        def observe(value: object, expected: object) -> dict:
            """Run actual closed validation and retain only its returned TEST reference."""
            result = validate(value, expected)
            published.append(result)
            return result
        reducer._original_guard.callback = lambda: published[0].update(pixelCount=99) if published else None
        with patch.object(module, "validate_gamut_reduction", side_effect=observe), self.assertRaisesRegex(ValueError, "result changed"):
            reducer.finish(fixture.original_terminal, fixture.measurement_terminal)
        fixture, reducer = self._completed()
        result = reducer.finish(fixture.original_terminal, fixture.measurement_terminal)
        result["binding"]["sourceId"] = "TEST changed"
        self.assertEqual(fixture.context["binding"]["sourceId"], "raw-1")
        self._failed(reducer, fixture)

    def _started(self) -> tuple:
        """Open one real reducer with only supplied synthetic data."""
        fixture = gamut_fixture()
        reducer = FramedFloatReducer(fixture.context, GamutGuard())
        reducer.begin_frame(fixture.frames[0], fixture.header())
        return fixture, reducer

    def _completed(self) -> tuple:
        """Complete one supplied payload but leave the two terminal records pending."""
        fixture, reducer = self._started()
        reducer.push(float_payload())
        reducer.end_frame()
        return fixture, reducer

    def _failed(self, reducer: FramedFloatReducer, fixture: object) -> None:
        """Every previously failed or finished operation must remain terminal."""
        with self.assertRaises(ValueError):
            reducer.finish(fixture.original_terminal, fixture.measurement_terminal)

    def test_signed_zero_summary_is_serialization_identical_across_chunks(self) -> None:
        """Normalize only zero extrema; the joined raw digest still binds zero bits."""
        fixture, payload = gamut_fixture(), float_payload((-0.0, 0.0, -0.0, 0.0))
        results = [json.dumps(fixture.run([payload], size), sort_keys=True) for size in (1, 4, 8, 16, 48)]
        self.assertEqual(len(set(results)), 1)
        self.assertNotEqual(fixture.run([payload])["joinedRecordsSha256"],
                            fixture.run([float_payload((0.0,) * 4)])["joinedRecordsSha256"])

    def test_vector_work_is_charged_to_same_original_guard_before_return(self) -> None:
        """Successful numeric work cannot return after its borrowed cutoff expires."""
        fixture, reducer = self._started()
        guard, accumulate = reducer._original_guard, samples._accumulate
        def slow(row: dict, values: np.ndarray) -> None:
            """Model bounded CPU time after running the actual vector computation."""
            accumulate(row, values)
            guard.now = guard.end
        with patch.object(samples, "_accumulate", side_effect=slow), self.assertRaises(TimeoutError):
            reducer.push(float_payload())
        self._failed(reducer, fixture)

    def test_invalid_initial_context_refuses_before_guard(self) -> None:
        """Unknown fields/digest syntax and legacy declarations cannot enter V2."""
        for change in ("extra", "digest", "legacy"):
            fixture, guard = gamut_fixture(), GamutGuard()
            if change == "legacy":
                fixture.context["declaration"]["schemaVersion"] = 1
            else:
                fixture.context["extra" if change == "extra" else "expectedRecordsSha256"] = "A" * 64
            with self.assertRaises(ValueError):
                FramedFloatReducer(fixture.context, guard)
            self.assertEqual(guard.calls, 0)

    def test_shorter_measurement_eof_cannot_hide_missing_original_coverage(self) -> None:
        """A clean one-frame float stream does not authenticate a two-frame source."""
        fixture = gamut_fixture(2)
        fixture.measurement_terminal.update(frames=1, payloadBytes=48)
        with self.assertRaisesRegex(ValueError, "coverage"):
            fixture.run([float_payload()])

    def test_successful_result_is_detached_from_validator_return(self) -> None:
        """A retained code-leaf alias cannot alter the successfully returned record."""
        fixture, reducer = self._completed()
        published, validate = [], module.validate_gamut_reduction
        def observed(value: object, expected: object) -> dict:
            """Preserve a TEST alias while still running actual closed validation."""
            published.append(validate(value, expected))
            return published[-1]
        with patch.object(module, "validate_gamut_reduction", side_effect=observed):
            result = reducer.finish(fixture.original_terminal, fixture.measurement_terminal)
        published[0]["channels"]["r"]["finiteCount"] = 99
        self.assertEqual(result["channels"]["r"]["finiteCount"], 4)
