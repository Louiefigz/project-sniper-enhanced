"""Concurrent visual declarations preserve exact windows and hard budgets."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from _visual_plan_fixture import (
    candidate, clone, opportunity, reseal_search_authority, visual_plan,
)
from contracts.schema_validator import SchemaValidationError, validate_document
from planner.visual_plan_allocator import allocate_visual_plan
from planner import catalog_receipt_pipeline
from planner.visual_plan_contract import (
    VisualPlanContractError, invalidation_inputs, validate_visual_plan,
)


def _visual(name: str, start: int, end: int) -> dict:
    """Make distinct visual developments without unrelated repeat conflicts."""
    choice = candidate(f"candidate:{name}", composition={
        "familyId": f"family:{name}", "development": f"Explain {name}."})
    return opportunity(name, start, [choice], timing={
        "startFrame": start, "endFrameExclusive": end})


def _layer(row: dict, *targets: str) -> dict:
    """Declare a purposeful pair without modifying either window."""
    row["layering"] = {"withOpportunityIds": list(targets),
                       "reason": "Title sits above the persistent diagram."}
    return row


def _paired_plan() -> dict:
    """Match a title and full-length supporting diagram at the same start."""
    return visual_plan(_visual("body", 0, 674),
                       _layer(_visual("opening", 0, 120), "body"))


class VisualPlanLayeringTests(unittest.TestCase):
    """Only explicit concurrent pairs bypass temporal breathing conflicts."""

    def test_opening_and_closing_overlay_preserve_full_underlayer(self) -> None:
        plan = visual_plan(_visual("body", 0, 674),
                           _layer(_visual("opening", 0, 120), "body"),
                           _layer(_visual("closing", 629, 674), "body"))
        allocated = allocate_visual_plan(plan)
        self.assertEqual(len(allocated["allocation"]["decisions"]), 3)
        self.assertEqual(allocated["opportunities"], plan["opportunities"])
        self.assertEqual(validate_document("visual-plan-v1.schema.json", allocated),
                         allocated)

    def test_undeclared_overlap_still_fails(self) -> None:
        plan = _paired_plan()
        del plan["opportunities"][1]["layering"]
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets"):
            allocate_visual_plan(plan)

    def test_same_start_pair_is_symmetric_and_order_independent(self) -> None:
        plan = _paired_plan()
        plan["opportunities"][0]["layering"] = {
            "withOpportunityIds": ["opening"], "reason": "Separate vertical regions."}
        del plan["opportunities"][1]["layering"]
        expected = allocate_visual_plan(plan)["allocation"]
        plan["opportunities"].reverse()
        reseal_search_authority(plan)
        self.assertEqual(allocate_visual_plan(plan)["allocation"], expected)

    def test_old_long_layer_cannot_be_hidden_by_short_overlay(self) -> None:
        plan = visual_plan(_visual("body", 0, 900),
                           _layer(_visual("opening", 10, 120), "body"),
                           _visual("closing", 700, 800))
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets.*closing"):
            allocate_visual_plan(plan)

    def test_every_active_overlap_requires_a_declared_pair(self) -> None:
        plan = visual_plan(_visual("body", 0, 900),
                           _layer(_visual("opening", 10, 120), "body"),
                           _layer(_visual("badge", 50, 100), "body"))
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets.*badge"):
            allocate_visual_plan(plan)

    def test_layering_never_skips_density_cap(self) -> None:
        plan = _paired_plan()
        plan["direction"]["density"]["maxVisualsPerSection"] = 1
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets"):
            allocate_visual_plan(plan)

    def test_layering_never_skips_family_cap(self) -> None:
        plan = _paired_plan()
        plan["direction"]["repetition"]["maxConsecutiveFamily"] = 1
        plan["opportunities"][1]["candidates"][0]["composition"]["familyId"] = "family:body"
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets"):
            allocate_visual_plan(plan)

    def test_layering_never_skips_identical_development_intent(self) -> None:
        plan = _paired_plan()
        first = plan["opportunities"][0]["candidates"][0]
        plan["opportunities"][1]["candidates"][0]["composition"] = clone(first["composition"])
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets"):
            allocate_visual_plan(plan)

    def test_sequential_breathing_room_still_applies_after_layers(self) -> None:
        plan = visual_plan(_visual("body", 0, 300),
                           _layer(_visual("opening", 0, 100), "body"),
                           _visual("next", 305, 340))
        plan["direction"]["density"]["minBreathingFrames"] = 10
        with self.assertRaisesRegex(VisualPlanContractError, "satisfies budgets.*next"):
            allocate_visual_plan(plan)
        plan["direction"]["density"]["minBreathingFrames"] = 5
        self.assertEqual(len(allocate_visual_plan(plan)["allocation"]["decisions"]), 3)

    def test_pair_with_nonvisual_choice_does_not_consume_visual_budget(self) -> None:
        presenter = opportunity("speaker", 0, [candidate("candidate:speaker", "presenter")])
        plan = visual_plan(presenter, _layer(_visual("title", 0, 100), "speaker"))
        plan["direction"]["density"]["maxVisualsPerSection"] = 1
        self.assertEqual(len(allocate_visual_plan(plan)["allocation"]["decisions"]), 2)

    def test_unknown_self_and_nonoverlapping_targets_fail(self) -> None:
        base = visual_plan(_visual("body", 0, 100), _visual("later", 100, 200))
        for target in ("unknown", "body", "later"):
            plan = clone(base)
            _layer(plan["opportunities"][0], target)
            with self.subTest(target=target), self.assertRaises(VisualPlanContractError):
                validate_visual_plan(plan)

    def test_malformed_layering_rejected_by_contract_and_schema(self) -> None:
        cases = [None, {}, {"withOpportunityIds": [], "reason": "Empty pair."},
                 {"withOpportunityIds": ["body", "body"], "reason": "Duplicate."},
                 {"withOpportunityIds": ["body"], "reason": ""},
                 {"withOpportunityIds": ["body"], "reason": " \n "},
                 {"withOpportunityIds": ["bad id"], "reason": "Invalid ID."},
                 {"withOpportunityIds": ["body"], "reason": "Bounded", "bypass": True},
                 {"withOpportunityIds": [f"o{i}" for i in range(9)], "reason": "Too many."}]
        base = _paired_plan()
        for layering in cases:
            plan = clone(base)
            plan["opportunities"][1]["layering"] = layering
            self._assert_invalid_in_both(plan)

    def _assert_invalid_in_both(self, plan: dict) -> None:
        with self.subTest(layering=plan["opportunities"][1]["layering"]):
            with self.assertRaises(VisualPlanContractError):
                validate_visual_plan(plan)
            with self.assertRaises(SchemaValidationError):
                validate_document("visual-plan-v1.schema.json", plan)

    def test_layering_reason_changes_only_visual_authority(self) -> None:
        plan = _paired_plan()
        before = invalidation_inputs(plan)
        plan["opportunities"][1]["layering"]["reason"] = "Revised layout purpose."
        after = invalidation_inputs(plan)
        self.assertNotEqual(before["pictureInputSha256"], after["pictureInputSha256"])
        self.assertNotEqual(before["visualPlanSha256"], after["visualPlanSha256"])
        self.assertEqual(before["upstreamAuthoritySha256"], after["upstreamAuthoritySha256"])

    def test_layering_helper_bytes_invalidate_issued_receipt_authority(self) -> None:
        before = catalog_receipt_pipeline.catalog_receipt_pipeline_authority()
        helper = "planner/visual_plan_layering.py"
        self.assertIn(helper, [row["path"] for row in before["files"]])
        original_read = catalog_receipt_pipeline.read_exact

        def changed_read(path: str, name: str, maximum: int) -> bytes:
            """Simulate a helper-only edit without changing the installed engine."""
            data = original_read(path, name, maximum)
            return data + b"\n" if path.endswith(helper) else data

        with patch.object(catalog_receipt_pipeline, "read_exact", changed_read):
            after = catalog_receipt_pipeline.catalog_receipt_pipeline_authority()
        self.assertNotEqual(before["sha256"], after["sha256"])


if __name__ == "__main__":
    unittest.main()
