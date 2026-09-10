"""Private source-grade intent must not silently acquire media/apply authority."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from _grade_contract_fixture import binding, declaration, recipe
from color.grade_contract import parse_declaration, parse_grade_recipe, parse_source_binding


class GradeContractTests(unittest.TestCase):
    """Closed schema, exact source identity and explicit lighting intent."""

    def test_identity_is_private_immutable_and_detached_from_input(self) -> None:
        source, context = binding(), declaration()
        value = recipe(source, context)
        parsed = parse_grade_recipe(value, source, context)
        self.assertFalse(parsed.applicable)
        self.assertTrue(parsed.corrections[0].identity)
        value["corrections"][0]["contrast"] = 1.1
        context["lightingGroups"][0]["description"] = "Changed later"
        self.assertEqual(parsed.corrections[0].contrast, 1)
        self.assertEqual(parsed.declaration.groups[0].description, "Synthetic neutral ramp")
        with self.assertRaises(FrozenInstanceError):
            parsed.look_name = "house-warm-v1"

    def test_one_frame_and_complete_multiple_groups(self) -> None:
        context = declaration(3)
        first = context["lightingGroups"][0]
        context["lightingGroups"] = [{**first, "id": "a", "endFrame": 1},
                                      {**first, "id": "b", "startFrame": 1}]
        source = binding(context)
        parsed = parse_grade_recipe(recipe(source, context), source, context)
        self.assertEqual([(group.start_frame, group.end_frame) for group in parsed.declaration.groups], [(0, 1), (1, 3)])

    def test_gap_overlap_reorder_duplicate_and_partial_coverage_reject(self) -> None:
        for delta in ("gap", "overlap", "reorder", "duplicate", "partial", "empty"):
            context = declaration()
            first = context["lightingGroups"][0]
            groups = [{**first, "id": "a", "endFrame": 150},
                      {**first, "id": "b", "startFrame": 150}]
            if delta == "gap": groups[1]["startFrame"] = 151
            if delta == "overlap": groups[1]["startFrame"] = 149
            if delta == "reorder": groups.reverse()
            if delta == "duplicate": groups[1]["id"] = "a"
            if delta == "partial": groups[0]["startFrame"] = 1
            if delta == "empty": groups[0]["endFrame"] = 0
            context["lightingGroups"] = groups
            source = binding(context)
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                parse_grade_recipe(recipe(source, context), source, context)

    def test_all_source_and_context_hashes_are_exact(self) -> None:
        source = binding()
        for key in source:
            value = recipe()
            value["source"][key] = {"sourceId": "raw-2", "fps": "30", "frameCount": 299}.get(key, "f" * 64)
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_grade_recipe(value, source, declaration())
        context = declaration()
        context["transformHistory"] = ["Changed declaration"]
        with self.assertRaisesRegex(ValueError, "declaration differs"):
            parse_grade_recipe(recipe(), source, context)

    def test_unknown_hdr_log_or_unknown_history_cannot_even_make_identity_recipe(self) -> None:
        for key, value in (("sourceProfile", "unknown"), ("sourceProfile", "hdr"),
                           ("sourceProfile", "log"), ("historyState", "unknown")):
            context = declaration()
            context[key] = value
            source = binding(context)
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_grade_recipe(recipe(source, context), source, context)

    def test_prose_history_retained_not_interpreted_as_transform(self) -> None:
        context = declaration()
        context.update(cameraProfile="Operator-declared camera setting", transformHistory=["Baked SDR delivery transform reviewed externally"])
        source = binding(context)
        parsed = parse_grade_recipe(recipe(source, context), source, context)
        self.assertEqual(parsed.declaration.transform_history, tuple(context["transformHistory"]))
        self.assertFalse(parsed.applicable)

    def test_dark_colored_and_unknown_only_allow_identity(self) -> None:
        for intent in ("dark", "colored", "unknown"):
            context = declaration()
            context["lightingGroups"][0]["intent"] = intent
            source = binding(context)
            value = recipe(source, context)
            self.assertTrue(parse_grade_recipe(value, source, context).corrections[0].identity)
            value["corrections"][0]["encodedLumaOffset"] = 0.01
            with self.subTest(intent=intent), self.assertRaises(ValueError):
                parse_grade_recipe(value, source, context)
            value = recipe(source, context)
            value["look"] = {"name": "house-warm-v1", "intensity": 0.1}
            with self.assertRaises(ValueError):
                parse_grade_recipe(value, source, context)

    def test_bounded_offsets_are_not_exposure_or_white_balance_fields(self) -> None:
        value = recipe()
        value["corrections"][0].update(encodedLumaOffset=0.04, contrast=1.1, saturation=0.9)
        parsed = parse_grade_recipe(value, binding(), declaration())
        self.assertFalse(parsed.corrections[0].identity)
        for extra in ("exposureEV", "whiteBalance", "filter", "lutPath", "approved"):
            changed = copy.deepcopy(value)
            changed["corrections"][0][extra] = 0
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_grade_recipe(changed, binding(), declaration())

    def test_nonfinite_boolean_string_and_out_of_range_numbers_reject(self) -> None:
        for amount in (True, "0.01", float("nan"), float("inf"), 0.04001, -0.04001, 10 ** 500):
            value = recipe()
            value["corrections"][0]["encodedLumaOffset"] = amount
            with self.subTest(amount=str(amount)[:20]), self.assertRaises(ValueError):
                parse_grade_recipe(value, binding(), declaration())

    def test_look_is_one_recipe_wide_named_intent_and_zero_canonicalizes(self) -> None:
        value = recipe()
        value["look"] = {"name": "house-warm-v1", "intensity": 0}
        self.assertEqual(parse_grade_recipe(value, binding(), declaration()).look_name, "neutral")
        value["look"]["intensity"] = 1
        self.assertEqual(parse_grade_recipe(value, binding(), declaration()).look_name, "house-warm-v1")
        for look in ({"name": "neutral", "intensity": 0.01}, {"name": "custom", "intensity": 0},
                     {"name": "house-warm-v1", "intensity": 1.01}):
            value["look"] = look
            with self.assertRaises(ValueError):
                parse_grade_recipe(value, binding(), declaration())

    def test_fractional_clock_must_be_canonical_exact_and_bounded(self) -> None:
        for fps in (29.97, "29.97", "60000/2002", "30/1", "0", "120", "030", True):
            source = binding()
            source["fps"] = fps
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                parse_source_binding(source)
        for count in (True, 0, 1.5, 1_296_001):
            source = binding()
            source["frameCount"] = count
            with self.assertRaises(ValueError):
                parse_source_binding(source)

    def test_schema_is_closed_at_every_user_facing_boundary(self) -> None:
        for target in ("recipe", "source", "look", "declaration", "group"):
            value, source, context = recipe(), binding(), declaration()
            rows = {"recipe": value, "source": value["source"], "look": value["look"],
                    "declaration": context, "group": context["lightingGroups"][0]}
            rows[target]["deliveryApproved"] = True
            with self.subTest(target=target), self.assertRaises(ValueError):
                parse_grade_recipe(value, source, context)

    def test_sampling_seconds_context_is_not_a_frame_declaration(self) -> None:
        context = declaration()
        context["lightingGroups"][0].update(start=0.0, end=10.01)
        source = binding(context)
        with self.assertRaises(ValueError):
            parse_grade_recipe(recipe(source, context), source, context)

    def test_invalid_nested_or_oversized_declaration_never_hashes(self) -> None:
        nested = []
        for _ in range(2000):
            nested = [nested]
        invalid = [("cameraProfile", nested), ("cameraProfile", "a" * 201),
                   ("transformHistory", [nested]), ("transformHistory", ["a"] * 21),
                   ("transformHistory", ["a" * 501]), ("lightingGroups", nested),
                   ("lightingGroups", [declaration()["lightingGroups"][0]] * 13)]
        source = parse_source_binding(binding())
        for key, value in invalid:
            context = declaration()
            context[key] = value
            with self.subTest(key=key), patch("color.grade_contract.digest") as hashed:
                with self.assertRaises(ValueError):
                    parse_declaration(context, source)
                hashed.assert_not_called()

    def test_invalid_notes_reject_before_hash_without_lossy_utf8(self) -> None:
        source = parse_source_binding(binding())
        for note in ("a" * 501, [["nested"]], "\ud800", "\udfff", "a\ud800z"):
            context = declaration()
            context["lightingGroups"][0]["description"] = note
            with self.subTest(note=repr(note)[:20]), patch("color.grade_contract.digest") as hashed:
                with self.assertRaises(ValueError):
                    parse_declaration(context, source)
                hashed.assert_not_called()

    def test_valid_declaration_hashes_exact_raw_fields_after_validation(self) -> None:
        context = declaration()
        context["cameraProfile"] = "  operator note  "
        source = parse_source_binding(binding(context))
        with patch("color.grade_contract.digest", return_value=source.declaration_sha256) as hashed:
            parsed = parse_declaration(context, source)
        hashed.assert_called_once_with(context)
        self.assertEqual(parsed.camera_profile, "  operator note  ")


if __name__ == "__main__":
    unittest.main()
