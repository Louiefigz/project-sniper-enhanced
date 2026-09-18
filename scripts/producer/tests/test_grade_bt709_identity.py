"""Pure supplemental geometry tests; supplied metadata is not decoded-source proof."""
from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import asdict

from _grade_bt709_identity_fixture import identity_lines, identity_records
from color.grade_bt709_identity import validate_bt709_identity_records
from color.grade_frame_adapter import validate_records
from test_grade_frame_adapter import decoder_terminal


class Bt709IdentityRecordTests(unittest.TestCase):
    """Keep the historical V1 class unchanged while closing opt-in geometry facts."""

    def setUp(self) -> None:
        """Allocate only small in-memory supplied raw metadata for each test."""
        self.source, self.declaration, self.probe, self.rows = identity_records()

    def validate(self) -> object:
        """Run the real supplemental consumer without IO, ownership or native work."""
        return validate_bt709_identity_records((self.source, self.declaration, self.probe),
                                               identity_lines(self.rows), decoder_terminal(3))

    def test_original_v1_schema_hash_and_nonzero_rational_clock_unchanged(self) -> None:
        """Supplemental geometry never inserts V2 fields into the old record hash."""
        old = validate_records((self.source, self.declaration, self.probe),
                               identity_lines(self.rows), decoder_terminal(3))
        result = self.validate()
        self.assertEqual(asdict(result.records), asdict(old))
        self.assertEqual(result.records.stream.first_pts, 900000)
        self.assertEqual(str(result.records.source.fps), "30000/1001")
        self.assertIsNone(result.records.stream.source_metadata)
        self.assertEqual(result.metadata.sample_aspect_ratio, "1:1")
        self.assertEqual(result.metadata.chroma_location, "left")
        self.assertEqual(result.metadata.decoded_frame_count, 3)
        self.assertFalse(result.metadata.pixel_orientation_measured)
        self.assertFalse(result.decoder_execution_proved or result.gamut_measured or result.grade_applicable)

    def test_missing_sar_preserves_legacy_acceptance_but_new_class_refuses(self) -> None:
        """No new metadata requirement is silently imposed on original V1 consumers."""
        del self.probe["streams"][0]["sample_aspect_ratio"]
        old = validate_records((self.source, self.declaration, self.probe),
                               identity_lines(self.rows), decoder_terminal(3))
        self.assertEqual(old.decoded_record_count, 3)
        with self.assertRaises(ValueError):
            self.validate()

    def test_header_and_every_frame_require_exact_square_sar(self) -> None:
        """Missing, unavailable, nonreduced, nonsquare and nonstring facts fail."""
        for value in (None, "N/A", "0:1", "2:2", "4:3", 1, True):
            self.probe["streams"][0]["sample_aspect_ratio"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()
        self.probe["streams"][0]["sample_aspect_ratio"] = "1:1"
        self.rows[-1]["sample_aspect_ratio"] = "4:3"
        with self.assertRaises(ValueError):
            self.validate()

    def test_unknown_or_changing_siting_is_not_a_codec_default(self) -> None:
        """Both independent header and all decoded rows require the same known siting."""
        for value in (None, "unknown", "N/A", "unavailable", "center"):
            self.rows[-1]["chroma_location"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()

    def test_rotation_tags_malformed_tags_and_non_h264_refuse(self) -> None:
        """Even zero-valued rotation metadata is outside the narrow absence-only class."""
        for tags in ({"rotate": "0"}, {"rotate": "90"}, {"ROTATE": "0"}, None, []):
            self.probe["streams"][0]["tags"] = tags
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                self.validate()
        self.probe["streams"][0]["tags"] = {}
        self.probe["streams"][0]["codec_name"] = "hevc"
        with self.assertRaises(ValueError):
            self.validate()

    def test_display_matrix_hdr_and_unknown_side_data_do_not_disappear(self) -> None:
        """Existing V1 side-data closure remains required, not bypassed by geometry."""
        for kind in ("Display Matrix", "Mastering display metadata", "unknown future effect"):
            self.probe["streams"][0]["side_data_list"] = [{"side_data_type": kind}]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.validate()

    def test_every_frame_keeps_existing_color_clock_and_coverage_guards(self) -> None:
        """Supplemental metadata cannot turn sparse or mismatched records into success."""
        original = deepcopy(self.rows)
        for key, value in (("color_transfer", "iec61966-2-4"), ("pkt_pts", 0), ("pkt_duration", 1)):
            self.rows = deepcopy(original)
            self.rows[-1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate()
        self.rows = original[:-1]
        with self.assertRaises(ValueError):
            self.validate()

    def test_terminal_warning_or_noninteger_success_cannot_finish(self) -> None:
        """The shared unchanged terminal validator requires exact warning-free EOF."""
        for key, value in (("stderrBytes", 1), ("exitCode", False), ("frames", True), ("reachedEof", False)):
            terminal = decoder_terminal(3)
            terminal[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_bt709_identity_records((self.source, self.declaration, self.probe),
                                                 identity_lines(self.rows), terminal)


if __name__ == "__main__":
    unittest.main()
