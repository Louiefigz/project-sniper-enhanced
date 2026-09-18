"""Data-only body read tests; no native media, full receipt authentication or approval."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _guided_presenter_body_read_fixture import PresenterBodyReadFixture
from guided_presenter_body_read import verify_presenter_body_prefix
from opening_prefix_contract import canonical_hash


class PresenterBodyReadTests(unittest.TestCase):
    """Genuine graph projections cannot be replaced by clip-only or rehydrated execution."""

    def setUp(self) -> None:
        """Retain tiny same-read file identities but explicit stub decoder facts."""
        self.fixture = PresenterBodyReadFixture()
        self.addCleanup(self.fixture.close)

    def verify(self, composition: dict | None = None) -> None:
        """Call production relational checks without mocking their graph or reader logic."""
        item = self.fixture
        verify_presenter_body_prefix(composition or item.composition, item.request, item.context)

    def test_original_full_and_opening_records_pass_without_new_decoder_or_live_owner(self) -> None:
        """Selected pictures are not redecoded merely to verify held evidence."""
        original = canonical_hash(self.fixture.composition)
        with patch("guided_presenter_observation.run_text", side_effect=AssertionError("no decoder")), \
                patch("guided_presenter_execution.OwnedPresenterExecution", side_effect=AssertionError("no owner")):
            self.verify()
        self.assertEqual(original, canonical_hash(self.fixture.composition))

    def test_schema_graph_policy_and_scope_mutations_fail(self) -> None:
        """A valid historical proof is not evidence for this new combined graph."""
        mutations = (("schemaVersion", 1), ("kind", "compositor-prefix-oracle"), ("fullGraphHash", "0" * 64),
                     ("openingGraphHash", "0" * 64), ("layerPolicy", {}), ("approvalObserved", True))
        for key, value in mutations:
            changed = deepcopy(self.fixture.composition)
            changed["prefixOracle"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.verify(changed)

    def test_future_windows_and_native_clock_are_not_omitted(self) -> None:
        """Later presentation intent remains part of the whole-video hash domain."""
        changed = deepcopy(self.fixture.composition)
        changed["prefixOracle"]["layerPolicy"]["fullPresenterWindows"] = 1
        with self.assertRaisesRegex(RuntimeError, "graph, layers"):
            self.verify(changed)
        request = replace(self.fixture.request, clock=replace(self.fixture.request.clock, total_frames=24))
        with self.assertRaises(RuntimeError):
            verify_presenter_body_prefix(self.fixture.composition, request, self.fixture.context)

    def test_missing_duplicate_reordered_or_wrong_sized_inputs_fail(self) -> None:
        """The input order is the actual original oracle order, not a latest stat lookup."""
        original = self.fixture.composition["prefixOracle"]["inputs"]
        candidates = [original[:-1], [*original, original[0]], original[::-1], deepcopy(original)]
        candidates[-1][-1]["size_bytes"] += 1
        for rows in candidates:
            changed = deepcopy(self.fixture.composition)
            changed["prefixOracle"]["inputs"] = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(RuntimeError, "inventory"):
                self.verify(changed)

    def test_incomplete_boolean_or_retimed_comparison_fails(self) -> None:
        """Every compared frame is required; booleans are not frame integers."""
        for role, key, value in (("fullGraphPrefix", "frameCount", True), ("core", "frameCount", 1),
                                 ("review", "startFrame", 1), ("review", "exactPreencodePixels", 1)):
            changed = deepcopy(self.fixture.composition)
            changed["prefixOracle"]["comparison"][role][key] = value
            with self.subTest(role=role, key=key), self.assertRaises(RuntimeError):
                self.verify(changed)

    def test_cold_graph_is_not_an_execution_capability(self) -> None:
        """Even a real-looking object in the presenter slot is rejected by the reader."""
        request = replace(self.fixture.request, presenter={"status": "complete"})
        with self.assertRaisesRegex(RuntimeError, "data-only"):
            verify_presenter_body_prefix(self.fixture.composition, request, self.fixture.context)

    def test_changed_saved_observation_or_original_picture_ref_fails(self) -> None:
        """The opening's authenticated graph and current observations are separately checked."""
        changed = deepcopy(self.fixture.composition)
        changed["prefixOracle"]["presenterObservations"][0]["source"]["sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.verify(changed)
        self.fixture.context.opening_pictures["presenterLayers"]["pictureRangesHash"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_final_callback_cannot_rewrite_composition_after_initial_check(self) -> None:
        """The final guard is not an opportunity to replace already verified evidence."""
        item, called = self.fixture, [0]

        def mutate() -> None:
            """Simulate late original-owner callback changing an outer retained field."""
            called[0] += 1
            item.original.guard()
            item.composition["output"]["sha256"] = "5" * 64

        context = replace(item.context, read=replace(item.context.read, guard=mutate))
        with self.assertRaisesRegex(RuntimeError, "changed"):
            verify_presenter_body_prefix(item.composition, item.request, context)
        self.assertGreater(called[0], 0)

    def test_last_guard_cannot_mutate_future_candidate_intent_after_cold_checks(self) -> None:
        """Regression for independent audit: final callbacks must rebind whole source intent."""
        item, calls, change_at = self.fixture, [0], [None]

        def guard() -> None:
            """Mutate only after the last ordinary owner callback has checked its files."""
            calls[0] += 1
            item.original.guard()
            if calls[0] == change_at[0]:
                item.original.inputs.documents["candidatePlan"]["presenterLayouts"][1]["endFrameExclusive"] -= 1

        context = replace(item.context, read=replace(item.context.read, guard=guard))
        verify_presenter_body_prefix(item.composition, item.request, context)
        change_at[0], calls[0] = calls[0], 0
        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            verify_presenter_body_prefix(item.composition, item.request, context)

    def test_float_held_tool_size_and_numeric_proof_substitutions_fail(self) -> None:
        """Canonical JSON number normalization cannot weaken exact metadata types."""
        item = self.fixture
        tool = replace(item.context.tools[0], size_bytes=float(item.context.tools[0].size_bytes))
        context = replace(item.context, tools=(tool, item.context.tools[1]))
        with self.assertRaisesRegex(RuntimeError, "exact bounded integer"):
            verify_presenter_body_prefix(item.composition, item.request, context)
        changed = deepcopy(item.composition)
        changed["prefixOracle"]["inputs"][-1]["size_bytes"] *= 1.0
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            self.verify(changed)
        changed = deepcopy(item.composition)
        changed["prefixOracle"]["layerPolicy"]["fullPresenterWindows"] = 2.0
        with self.assertRaisesRegex(RuntimeError, "graph, layers"):
            self.verify(changed)


if __name__ == "__main__":
    unittest.main()
