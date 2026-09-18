"""Golden and adversarial checks for exact P2 dialogue authority."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.dialogue_authority import (
    DialogueAuthorityError,
    compile_dialogue_map,
    dialogue_track_hash,
    parse_dialogue_map,
    parse_dialogue_track,
    validate_dialogue_authority,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "dialogue-authority-v1.json"


class DialogueAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_golden_track_compiles_to_exact_cross_language_map(self) -> None:
        track, dialogue_map = validate_dialogue_authority(
            self.fixture["track"], self.fixture["map"])
        self.assertEqual(dialogue_track_hash(track), self.fixture["trackHash"])
        self.assertEqual(compile_dialogue_map(track), dialogue_map)
        self.assertEqual(
            dialogue_map["totalOutputSamples"], 180 * 48_000 // 30)

    def test_44100_boundaries_and_requested_speed_are_exact(self) -> None:
        entries = parse_dialogue_map(self.fixture["map"])["entries"]
        by_id = {row["dialogueSegmentId"]: row for row in entries}
        self.assertEqual(
            by_id["dialogue-b-j-handle"]
            ["normalizedSourceSampleRange"]["endSampleExclusive"],
            by_id["dialogue-b-primary"]
            ["normalizedSourceSampleRange"]["startSample"])
        self.assertEqual(
            by_id["dialogue-b-primary"]
            ["normalizedSourceSampleRange"]["endSampleExclusive"],
            by_id["dialogue-b-l-handle"]
            ["normalizedSourceSampleRange"]["startSample"])
        self.assertEqual(
            by_id["dialogue-c-primary"]["effectiveSpeed"],
            {"numerator": "5", "denominator": "4"})

    def test_both_closed_schemas_accept_the_golden_documents(self) -> None:
        self.assertEqual(validate_document(
            "dialogue-track-v1.schema.json", self.fixture["track"]),
            self.fixture["track"])
        self.assertEqual(validate_document(
            "dialogue-map-v1.schema.json", self.fixture["map"]),
            self.fixture["map"])

    def test_float_and_legacy_millisecond_fields_never_enter_authority(self) -> None:
        for mutation in ("float-speed", "audio-lead-ms"):
            with self.subTest(mutation=mutation):
                track = copy.deepcopy(self.fixture["track"])
                if mutation == "float-speed":
                    track["segments"][0]["speed"] = 1.0
                else:
                    track["segments"][1]["audioLeadMs"] = 100
                with self.assertRaises(DialogueAuthorityError):
                    parse_dialogue_track(track)

    def test_noncanonical_order_and_disconnected_handle_fail_closed(self) -> None:
        unordered = copy.deepcopy(self.fixture["track"])
        unordered["segments"][0], unordered["segments"][1] = (
            unordered["segments"][1], unordered["segments"][0])
        with self.assertRaisesRegex(DialogueAuthorityError, "ordered"):
            parse_dialogue_track(unordered)
        disconnected = copy.deepcopy(self.fixture["track"])
        disconnected["segments"][1]["seamSample"] -= 1
        with self.assertRaisesRegex(DialogueAuthorityError, "seam"):
            parse_dialogue_track(disconnected)

    def test_clock_and_speed_mismatches_fail_before_compilation(self) -> None:
        bad_clock = copy.deepcopy(self.fixture["track"])
        bad_clock["totalOutputSamples"] -= 1
        with self.assertRaisesRegex(DialogueAuthorityError, "B\\(total frames\\)"):
            parse_dialogue_track(bad_clock)
        bad_speed = copy.deepcopy(self.fixture["track"])
        bad_speed["segments"][3]["speed"] = {
            "numerator": "6", "denominator": "5"}
        with self.assertRaisesRegex(DialogueAuthorityError, "speed"):
            parse_dialogue_track(bad_speed)

    def test_stale_map_derivation_and_track_binding_fail_closed(self) -> None:
        stale = copy.deepcopy(self.fixture["map"])
        stale["entries"][2]["normalizedSourceSampleRange"][
            "endSampleExclusive"] -= 1
        with self.assertRaisesRegex(DialogueAuthorityError, "stale derived"):
            parse_dialogue_map(stale)
        foreign = copy.deepcopy(self.fixture["map"])
        foreign["dialogueTrackHash"] = "c" * 64
        with self.assertRaisesRegex(DialogueAuthorityError, "exactly bind"):
            validate_dialogue_authority(self.fixture["track"], foreign)

    def test_schema_requires_handle_fields_and_rejects_unknown_fields(self) -> None:
        missing = copy.deepcopy(self.fixture["track"])
        del missing["segments"][1]["seamSample"]
        with self.assertRaises(SchemaValidationError):
            validate_document("dialogue-track-v1.schema.json", missing)
        extra = copy.deepcopy(self.fixture["map"])
        extra["entries"][0]["audioLeadMs"] = 50
        with self.assertRaises(SchemaValidationError):
            validate_document("dialogue-map-v1.schema.json", extra)


if __name__ == "__main__":
    unittest.main(verbosity=2)
