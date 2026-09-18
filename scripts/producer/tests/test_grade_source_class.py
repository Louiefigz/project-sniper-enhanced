"""Streaming supplied-frame proof cannot be replaced by tags or sparse samples."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError

from _grade_contract_fixture import binding, declaration, frame, stream, terminal
from color.grade_source_class import SourceFrameValidator, SourceRecordValidation


def validator(count: int = 300, origin: int = 900_000) -> tuple:
    """Fresh pure validator, not a decoder or executable media authority."""
    context = declaration(count)
    source = binding(context)
    observed = stream(source, origin)
    return SourceFrameValidator(source, context, observed), source, observed


class GradeSourceClassTests(unittest.TestCase):
    """Exact whole-source cadence and all-frame class; poison on any failure."""

    def test_full_fractional_clock_preserves_nonzero_and_negative_origins(self) -> None:
        for origin in (900_000, -90_000, 0):
            scan, source, observed = validator(origin=origin)
            for index in range(source["frameCount"]):
                scan.add_frame(frame(index, observed))
            result = scan.finish(terminal(source))
            self.assertEqual(result.stream.first_pts, origin)
            self.assertEqual(result.decoded_record_count, 300)
            self.assertTrue(result.record_validation_only)
            self.assertFalse(result.decoder_execution_proved)
            self.assertFalse(result.grade_applicable)
            self.assertFalse(result.delivery_approved)
            with self.assertRaises(FrozenInstanceError):
                result.delivery_approved = True
            with self.assertRaises(TypeError):
                SourceRecordValidation(result.source, result.stream, 300, "a" * 64, delivery_approved=True)

    def test_late_metadata_drift_after_first_fifty_seconds_is_rejected(self) -> None:
        scan, source, observed = validator(count=2000)
        for index in range(1800):
            scan.add_frame(frame(index, observed))
        late = frame(1800, observed)
        late["transfer"] = "smpte2084"
        with self.assertRaisesRegex(ValueError, "changing decoded color"):
            scan.add_frame(late)
        with self.assertRaisesRegex(ValueError, "failed"):
            scan.add_frame(frame(1800, observed))
        with self.assertRaisesRegex(ValueError, "failed"):
            scan.finish(terminal(source))

    def test_every_unconverted_frame_color_field_and_corruption_fact_matters(self) -> None:
        mutations = {"range": "pc", "matrix": "bt2020nc", "transfer": None,
                     "primaries": "unknown", "pixelFormat": "yuv420p10le", "hdrSignaled": True,
                     "corrupt": True, "decodeErrorFlags": 1, "interlaced": True,
                     "repeatPict": 1, "width": 1280, "streamIndex": 1}
        for key, value in mutations.items():
            scan, _source, observed = validator()
            row = frame(0, observed)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                scan.add_frame(row)

    def test_false_boolean_and_integer_coercions_are_not_facts(self) -> None:
        for key, value in (("corrupt", 0), ("hdrSignaled", 0), ("decodeErrorFlags", False),
                           ("repeatPict", False), ("index", False), ("pts", "900000")):
            scan, _source, observed = validator()
            row = frame(0, observed)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                scan.add_frame(row)

    def test_pts_drift_duplicate_duration_and_variable_cadence_reject(self) -> None:
        for key, value in (("pts", 900_001), ("durationTicks", 1000), ("durationTicks", 0)):
            scan, _source, observed = validator()
            row = frame(0, observed)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                scan.add_frame(row)
        scan, _source, observed = validator()
        scan.add_frame(frame(0, observed))
        duplicate = frame(1, observed)
        duplicate["pts"] = observed["firstPts"]
        with self.assertRaises(ValueError):
            scan.add_frame(duplicate)

    def test_subset_gaps_reordered_and_extra_frames_never_finish(self) -> None:
        scan, source, observed = validator()
        scan.add_frame(frame(0, observed))
        with self.assertRaisesRegex(ValueError, "coverage"):
            scan.finish(terminal(source))
        for index in (1, 5, 299):
            scan, _source, observed = validator()
            with self.assertRaises(ValueError):
                scan.add_frame(frame(index, observed))
        scan, source, observed = validator(count=1)
        scan.add_frame(frame(0, observed))
        with self.assertRaisesRegex(ValueError, "extra"):
            scan.add_frame(frame(1, observed))

    def test_clean_eof_and_zero_exit_errors_are_mandatory(self) -> None:
        for key, value in (("reachedEof", False), ("decoderExitCode", 1),
                           ("decoderErrorCount", 1), ("decoderExitCode", False),
                           ("decoderWarningCount", 1), ("decoderWarningCount", False),
                           ("decoderErrorObservationPolicy", "ignored-warning-policy")):
            scan, source, observed = validator(count=1)
            scan.add_frame(frame(0, observed))
            end = terminal(source)
            end[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                scan.finish(end)

    def test_all_after_source_and_declaration_identities_must_match(self) -> None:
        for key in binding():
            scan, source, observed = validator(count=1)
            scan.add_frame(frame(0, observed))
            end = terminal(copy.deepcopy(source))
            end["source"][key] = {"sourceId": "raw-2", "fps": "30", "frameCount": 2}.get(key, "f" * 64)
            with self.subTest(key=key), self.assertRaises(ValueError):
                scan.finish(end)

    def test_stream_tags_alone_or_unrepresentable_timebase_are_insufficient(self) -> None:
        source, context = binding(), declaration()
        mutations = {"timeBase": "1/1000", "fps": "29.97", "frameCount": 299,
                     "pixelFormat": "yuv444p", "range": None, "progressive": False,
                     "videoStreamCount": 2, "firstPts": 2 ** 53 - 1}
        for key, value in mutations.items():
            observed = stream(source)
            observed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                SourceFrameValidator(source, context, observed)
        scan, source, _observed = validator()
        with self.assertRaisesRegex(ValueError, "coverage"):
            scan.finish(terminal(source))

    def test_supplied_records_hash_is_deterministic_and_origin_bound(self) -> None:
        hashes = []
        for origin in (10, 10, 11):
            scan, source, observed = validator(count=2, origin=origin)
            for index in range(2):
                scan.add_frame(frame(index, observed))
            hashes.append(scan.finish(terminal(source)).records_sha256)
        self.assertEqual(hashes[0], hashes[1])
        self.assertNotEqual(hashes[0], hashes[2])

    def test_closed_records_and_terminal_state_prevent_repair_after_finish(self) -> None:
        scan, source, observed = validator(count=1)
        bad = frame(0, observed)
        bad["samplingOnly"] = True
        with self.assertRaises(ValueError):
            scan.add_frame(bad)
        scan, source, observed = validator(count=1)
        scan.add_frame(frame(0, observed))
        scan.finish(terminal(source))
        for action in (lambda: scan.finish(terminal(source)), lambda: scan.add_frame(frame(0, observed))):
            with self.assertRaisesRegex(ValueError, "finished"):
                action()


if __name__ == "__main__":
    unittest.main()
