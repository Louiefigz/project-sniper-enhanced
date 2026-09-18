"""Adversarial V7 music projection contracts; no media, rights or consent tests."""
from __future__ import annotations

from copy import deepcopy
from itertools import product
import unittest

from _guided_proposal_music_fixture import music_operation, source_entry, values
from guided_media_profile import CAPTION_SHORT_PROFILE
from guided_proposal_music import MUSIC_SCOPE, guided_music_policy, validate_requested_music, verify_music_admission
from guided_proposal_reframe import validate_requested_manual_crop


class GuidedMusicTests(unittest.TestCase):
    """Exact bytes/metadata and original operations remain independent authorities."""

    def test_exact_music_only_projection_preserves_every_supplied_input(self) -> None:
        """A no-crop7 request still gets a complete real-schema semantic check."""
        rows = values()
        before = deepcopy(rows)
        selected = validate_requested_music(*rows)
        self.assertEqual(selected, rows[3]["music"][0])
        self.assertEqual(rows, before)
        selected["duration"] = 99
        self.assertEqual(rows, before)

    def test_actual_seven_crop_caption_music_positions_are_not_relabelled(self) -> None:
        """Shared crop validation accepts actual7 while preserving music at index0."""
        plan, result, request, manifest = values(crop=True)
        before = deepcopy(request)
        validate_requested_music(plan, result, request, manifest)
        self.assertTrue(validate_requested_manual_crop(plan, result, request, CAPTION_SHORT_PROFILE))
        self.assertEqual(request, before)
        self.assertEqual([row["type"] for row in request["proposal"]["operations"]],
                         ["music-bed-full-program", "reframe-manual-short", "captions-full-program"])

    def test_candidate_only_changes_or_extra_fields_do_not_gain_authority(self) -> None:
        """Recomputed candidate hashes cannot introduce an unrequested bed or knob."""
        changes = [None, {}, {"enabled": False}, {"enabled": True, "assetId": "TEST-bed", "gapDb": 12, "duck": True}]
        changes += [{**values()[1]["music"], key: value} for key, value in (("path", None), ("duck", 1), ("variants", []))]
        for music in changes:
            plan, result, request, manifest = values()
            result["music"] = music
            request["candidate"] = deepcopy(result)
            with self.subTest(music=music), self.assertRaises(RuntimeError):
                validate_requested_music(plan, result, request, manifest)
        plan, result, request, manifest = values()
        del result["music"]
        with self.assertRaises(RuntimeError):
            validate_requested_music(plan, result, request, manifest)

    def test_all_historical_versions_preserve_presence_and_value(self) -> None:
        """Previously accepted null/off/music objects are not silently replaced."""
        inherited_values = (None, {}, {"enabled": False}, {"enabled": True, "assetId": "existing"})
        for version, inherited in product((2, 3, 4, 5, 6), inherited_values):
            plan, result, request, manifest = values(music=False)
            request["proposal"]["schemaVersion"] = version
            plan["music"], result["music"] = deepcopy(inherited), deepcopy(inherited)
            self.assertIsNone(validate_requested_music(plan, result, request, manifest))
            del result["music"]
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                validate_requested_music(plan, result, request, manifest)
            del plan["music"]
            result["music"] = deepcopy(inherited)
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                validate_requested_music(plan, result, request, manifest)

    def test_noop_seven_requires_policy_and_preserves_inherited_music(self) -> None:
        """No-op7 cannot skip policy verification or remove an existing selection."""
        plan, result, request, manifest = values(music=False)
        plan["music"] = result["music"] = {"enabled": False}
        self.assertIsNone(validate_requested_music(plan, result, request, manifest))
        request["evidence"].clear()
        with self.assertRaisesRegex(RuntimeError, "policy"):
            validate_requested_music(plan, result, request, manifest)

    def test_unknown_or_coerced_versions_cannot_pose_as_historical_noops(self) -> None:
        """Only actual supported integer proposals can inherit unchanged music."""
        proposals = [None, [], {}] + [{"schemaVersion": value} for value in (True, 7.0, "7", 1, 8, None)]
        for proposal in proposals:
            plan, result, request, manifest = values(music=False)
            request["proposal"] = proposal
            with self.assertRaisesRegex(RuntimeError, "integer proposal"):
                validate_requested_music(plan, result, request, manifest)
        for version in (None, True, 7.0, "7", 6):
            plan, result, request, manifest = values()
            request["evidence"]["schemaVersion"] = version
            with self.assertRaisesRegex(RuntimeError, "policy"):
                validate_requested_music(plan, result, request, manifest)

    def test_new_music_needs_exact_existing_optin_and_absent_inherited_field(self) -> None:
        """A false target flag or even inherited null blocks music addition."""
        plan, result, request, manifest = values()
        plan["target"]["music"] = False
        request["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
        with self.assertRaisesRegex(RuntimeError, "target.music"):
            validate_requested_music(plan, result, request, manifest)
        for inherited in (None, {}, {"enabled": False}, {"enabled": True}):
            plan, result, request, manifest = values()
            plan["music"] = inherited
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                validate_requested_music(plan, result, request, manifest)

    def test_present_music_metadata_is_boolean_even_on_seven_noops(self) -> None:
        """Null, numeric/string booleans and other shapes cannot be coerced to disabled."""
        invalid = (None, 0, 1, 0.0, 1.0, "false", "true", [], {})
        for flag in invalid:
            plan, result, request, manifest = values(music=False)
            plan["target"]["music"] = result["target"]["music"] = flag
            with self.assertRaisesRegex(RuntimeError, "actual boolean"):
                guided_music_policy(plan, manifest)
            with self.assertRaisesRegex(RuntimeError, "actual boolean"):
                validate_requested_music(plan, result, request, manifest)

    def test_historical_metadata_is_not_reinterpreted_as_new_mirrored_authority(self) -> None:
        """Versions2..6 preserve inherited music exactly without adding a new target gate."""
        for version, flag in product((2, 3, 4, 5, 6), (None, 0, 1, "true", [], {})):
            plan, result, request, manifest = values(music=False)
            plan["target"]["music"] = result["target"]["music"] = flag
            request["proposal"]["schemaVersion"] = version
            before = deepcopy((plan, result, request, manifest))
            self.assertIsNone(validate_requested_music(plan, result, request, manifest))
            self.assertEqual((plan, result, request, manifest), before)
            result["music"] = {"enabled": True, "assetId": "unrequested"}
            with self.assertRaisesRegex(RuntimeError, "inherited music"):
                validate_requested_music(plan, result, request, manifest)

    def test_missing_false_or_true_metadata_is_preserved_without_a_new_bed(self) -> None:
        """A missing mirror stays absent/false; validation never writes accepted intent."""
        for version, flag in product((2, 3, 4, 5, 6, 7), (None, False, True)):
            plan, result, request, manifest = values(music=False)
            plan["target"]["music"] = result["target"]["music"] = flag
            if flag is None:
                del plan["target"]["music"], result["target"]["music"]
            request["proposal"]["schemaVersion"] = version
            policy = guided_music_policy(plan, manifest)
            request["evidence"]["musicPolicy"] = policy
            before = deepcopy((plan, result, request, manifest))
            self.assertIs(policy["acceptedMusicEnabled"], flag is True)
            self.assertIsNone(validate_requested_music(plan, result, request, manifest))
            self.assertEqual((plan, result, request, manifest), before)

    def test_music_payload_type_numeric_and_field_bounds_fail_closed(self) -> None:
        """Booleans/nonfinite/large numbers and unrelated source controls are rejected."""
        changes = [{"schemaVersion": value} for value in (True, 1.0, "1", 2)]
        changes += [{"gapDb": value} for value in (True, "11", float("nan"), float("inf"), 2.99, 40.01, 10**400)]
        changes += [{"duck": value} for value in (False, 1, "true")]
        changes += [{"assetId": value} for value in ("", " ", "x"*129, 12, None)]
        changes += [{"path": "/TEST/forbidden"}, {"coverage": "full-program"}]
        for change in changes:
            plan, result, request, manifest = values()
            request["proposal"]["operations"][0]["music"].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_music(plan, result, request, manifest)
        for gap in (3, 40, 11.5):
            plan, result, request, manifest = values()
            request["proposal"]["operations"][0]["music"]["gapDb"] = result["music"]["gapDb"] = gap
            validate_requested_music(plan, result, request, manifest)

    def test_missing_duplicate_mixed_and_nonnullable_operations_are_rejected(self) -> None:
        """Every original operation owns exactly its declared payload and null others."""
        changes = [{"music": None}, {"captions": {"schemaVersion": 1, "preset": "producer-config-line-v1",
            "coverage": "all-kept-transcript-words", "suppression": "none"}}, {"grade": "warm"}, {"reason": "        "}]
        for change in changes:
            plan, result, request, manifest = values()
            request["proposal"]["operations"][0].update(change)
            with self.assertRaises((RuntimeError, ValueError)):
                validate_requested_music(plan, result, request, manifest)
        for duplicate in (True, False):
            plan, result, request, manifest = values()
            if duplicate:
                request["proposal"]["operations"].append(music_operation())
                request["proposal"]["clauses"][0]["operationIndices"].append(2)
            else:
                del request["proposal"]["operations"][1]["music"]
            with self.assertRaises((RuntimeError, ValueError)):
                validate_requested_music(plan, result, request, manifest)
        plan, result, request, manifest = values()
        request["proposal"]["operations"][1]["music"] = music_operation()["music"]
        with self.assertRaises(RuntimeError):
            validate_requested_music(plan, result, request, manifest)

    def test_request_coverage_and_actual_indices_cannot_be_rehashed_away(self) -> None:
        """Changed raw text, omitted operations and UTF-16 span changes are terminal."""
        for field in ("raw", "span", "index", "quote"):
            plan, result, request, manifest = values()
            clause = request["proposal"]["clauses"][0]
            if field == "raw":
                request["rawRequest"]["rawIntent"] += " Added intent."
            if field == "span":
                clause["end"] -= 1
            if field == "index":
                clause["operationIndices"] = [1]
            if field == "quote":
                clause["quote"] = "Different original request."
            with self.assertRaises(RuntimeError):
                validate_requested_music(plan, result, request, manifest)

    def test_policy_is_closed_ordered_and_never_infers_rights(self) -> None:
        """Full metadata matches TS, preserving asset order and excluded builtin count."""
        plan, _result, _request, manifest = values()
        manifest["music"].append({"id": "builtin", "source": "builtin", "licensed": True})
        row = manifest["music"][0]
        row["licensed"] = True
        expected = {"schemaVersion": 1, "scope": MUSIC_SCOPE, "acceptedMusicEnabled": True,
            "gapDb": {"minimum": 3, "maximum": 40}, "duck": True,
            "fitting": "full-program-loop-crossfade-and-ending-fade", "excludedBuiltinCount": 1,
            "assets": [{"assetId": "TEST-bed", "sourceSha256": "a"*64, "sourceSizeBytes": 128,
                        "admissionReceiptSha256": "b"*64, "durationS": 12.5, "rights": "unverified"}]}
        self.assertEqual(guided_music_policy(plan, manifest), expected)
        manifest["music"].insert(0, {**row, "id": "first"})
        self.assertEqual([item["assetId"] for item in guided_music_policy(plan, manifest)["assets"]], ["first", "TEST-bed"])

    def test_catalog_bounds_and_all_rows_are_checked_even_when_not_selected(self) -> None:
        """Excluded rows still need unique IDs; admitted fields have exact numeric types."""
        changes = [{"sourceSizeBytes": value} for value in (True, 0, -1, 1.5, 2**53, 10**400)]
        changes += [{"duration": value} for value in (True, 0, float("nan"), float("inf"), 10**400)]
        changes += [{key: None} for key in ("originalPath", "path", "admissionReceiptPath", "sourceSha256", "admissionReceiptSha256")]
        for change in changes:
            plan, _result, _request, manifest = values()
            manifest["music"].append({**manifest["music"][0], "id": "unselected", **change})
            with self.assertRaises(RuntimeError):
                guided_music_policy(plan, manifest)
        for rows in ({}, [None], [{"id": "x", "source": "builtin"}]*2,
                     [{"id": str(index), "source": "builtin"} for index in range(129)]):
            with self.assertRaises(RuntimeError):
                guided_music_policy(values()[0], {"music": rows})

    def test_stale_policy_and_builtin_selection_cannot_enter_the_music_bus(self) -> None:
        """Even no-op requests bind excluded counts and all original asset metadata."""
        for field, value in (("sourceSizeBytes", 129), ("duration", 13), ("sourceSha256", "c"*64)):
            plan, result, request, manifest = values()
            manifest["music"][0][field] = value
            with self.assertRaisesRegex(RuntimeError, "policy"):
                validate_requested_music(plan, result, request, manifest)
        plan, result, request, manifest = values()
        manifest["music"] = [{"id": "TEST-bed", "source": "builtin"}]
        request["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
        with self.assertRaisesRegex(RuntimeError, "catalog"):
            validate_requested_music(plan, result, request, manifest)

    def test_selected_actual_admission_lane_paths_hash_and_size_are_exact(self) -> None:
        """Source-set facts already verified by the real gate cannot be transplanted."""
        selection = values()[3]["music"][0]
        entry = source_entry(selection)
        verify_music_admission(selection, [entry])
        for key, value in (("lane", "source"), ("mediaKind", "still-image"), ("sizeBytes", 129),
                           ("snapshotPath", "/TEST/another"), ("originalPath", "/TEST/another.wav"),
                           ("sha256", "c"*64), ("admissionReceiptSha256", "d"*64)):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "source-set"):
                verify_music_admission(selection, [{**entry, key: value}])
        for entries in ([], [entry, entry], [{**entry, "additional": True}]):
            with self.assertRaises(RuntimeError):
                verify_music_admission(selection, entries)


if __name__ == "__main__":
    unittest.main()
