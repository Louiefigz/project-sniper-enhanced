"""Cold presenter relations beneath TEST receipt metadata, never media approval."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _guided_presenter_read_fixture import PresenterReadFixture
import guided_presenter_read as module
from opening_prefix_contract import canonical_hash


class PresenterReadTests(unittest.TestCase):
    """Validate actual V8 joins and inert projections, with no decoder or renderer."""

    def setUp(self) -> None:
        """Create original attestations via controlled stub output and real tiny pins."""
        self.fixture = PresenterReadFixture()
        self.addCleanup(self.fixture.close)

    def test_cold_roundtrip_preserves_future_windows_without_live_owner_or_decode(self) -> None:
        """Raw hashes remain original attestations; exact graph metadata is reconstructed."""
        value = self.fixture
        with patch("guided_presenter_observation.run_text") as probe, \
                patch("headless.external_media_snapshot._hash_descriptor") as source_hash, \
                patch("guided_presenter_execution.OwnedPresenterExecution.__init__") as owner:
            result = module.verify_opening_presenter_layers(value.pictures, value.context, ((), None))
        probe.assert_not_called()
        source_hash.assert_not_called()
        owner.assert_not_called()
        self.assertFalse(result.executable)
        self.assertIn("not-redecoded", result.scope)
        self.assertEqual(len(result.full["windows"]), 2)
        self.assertEqual(len(result.opening["windows"]), 1)
        self.assertEqual(result.opening["windows"][0]["frameRange"], [2, 18])
        self.assertEqual(result.opening["canvas"]["total_frames"], 48)
        self.assertEqual(canonical_hash(result.full), value.pictures["presenterLayers"]["fullPresenterGraphHash"])
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.observations[0]["framesSha256"], value.records[0]["framesSha256"])

    def test_legacy_absence_stays_absent_and_explicit_null_is_not_absence(self) -> None:
        """No old record receives a new profile or a silently dropped presenter field."""
        context = self.fixture.noop_context()
        self.assertIsNone(module.read_presenter_graphs(None, context))
        self.assertIsNone(module.verify_opening_presenter_layers({}, context, ((), None)))
        with self.assertRaisesRegex(RuntimeError, "legacy"):
            module.verify_opening_presenter_layers({"presenterLayers": None}, context, ((), None))
        with self.assertRaisesRegex(RuntimeError, "attestations"):
            module.verify_opening_presenter_layers({"ranges": {}}, self.fixture.context, ((), None))

    def test_every_root_layer_binding_is_checked_not_merely_self_hashes(self) -> None:
        """A coherent edited graph/summary cannot replace independently held arguments."""
        original, context = self.fixture.pictures, self.fixture.context
        changes = {"schemaVersion": True, "scope": "approved", "candidatePlanHash": "f" * 64,
            "authorityHash": "f" * 64, "fullPresenterGraphHash": "f" * 64, "layerPolicy": "legacy",
            "deliveryApproved": True, "captionClearanceVerified": True, "pictureRangesHash": "f" * 64}
        for key, value in changes.items():
            changed = deepcopy(original)
            changed["presenterLayers"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "reconstructed"):
                module.verify_opening_presenter_layers(changed, context, ((), None))
        changed = deepcopy(original)
        changed["presenterLayers"]["graph"]["presenter"]["windows"][0]["frameRange"][1] = 17
        changed["presenterLayers"]["graphHash"] = canonical_hash(changed["presenterLayers"]["graph"])
        with self.assertRaisesRegex(RuntimeError, "reconstructed"):
            module.verify_opening_presenter_layers(changed, context, ((), None))

    def test_range_bytes_base_and_independently_supplied_clip_inventory_must_match(self) -> None:
        """Output verification stays separate, but its exact recorded identity is bound."""
        pictures = deepcopy(self.fixture.pictures)
        pictures["ranges"]["core"]["TEST"] = "changed output proof"
        contexts = [self.fixture.context, replace(self.fixture.context,
            base=replace(self.fixture.base, sha256="b" * 64))]
        for context in contexts:
            with self.subTest(context=context), self.assertRaisesRegex(RuntimeError, "reconstructed"):
                module.verify_opening_presenter_layers(pictures, context, ((), None))
        with self.assertRaisesRegex(RuntimeError, "reconstructed"):
            module.verify_opening_presenter_layers(self.fixture.pictures, self.fixture.context,
                                                   (({"TEST": "independently held extra clip"},), None))

    def test_original_capture_source_tool_and_deadline_must_still_be_current(self) -> None:
        """Retained successful hashes cannot repair changed source or missing capture."""
        context = replace(self.fixture.context, inputs=replace(self.fixture.inputs, verified_media=None))
        with self.assertRaisesRegex(RuntimeError, "initial source"):
            module.read_presenter_graphs(self.fixture.records, context)
        self.fixture.probe.path.write_bytes(b"changed TEST original source")
        with self.assertRaisesRegex(RuntimeError, "snapshot identity changed"):
            module.read_presenter_graphs(self.fixture.records, self.fixture.context)
        self.fixture.probe.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            module.read_presenter_graphs(self.fixture.records, self.fixture.context)

    def test_final_callback_mutation_cannot_return_previously_verified_data(self) -> None:
        """The last callback cannot change the receipt after its comparisons already ran."""
        count = 0

        def count_calls() -> None:
            """Count exact current pure-reader boundary calls without any timing reset."""
            nonlocal count
            count += 1
            self.fixture.guard()

        context = replace(self.fixture.context, guard=count_calls)
        module.verify_opening_presenter_layers(self.fixture.pictures, context, ((), None))
        final_count, count = count, 0

        def mutate_final() -> None:
            """Mutate only after the original final source/clock callback succeeds."""
            count_calls()
            if count == final_count:
                self.fixture.pictures["ranges"]["review"]["TEST"] = "late substitution"

        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            module.verify_opening_presenter_layers(self.fixture.pictures,
                replace(context, guard=mutate_final), ((), None))

    def test_capture_contents_cannot_change_in_place_behind_a_frozen_record(self) -> None:
        """Object identity alone is not a durable source-verification binding."""
        captured = self.fixture.inputs.verified_media

        def mutate() -> None:
            """Keep the same object but change its original source hash after caller checks."""
            self.fixture.guard()
            row = replace(captured.snapshots[0], sha256="d" * 64)
            object.__setattr__(captured, "snapshots", (row,))

        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            module.read_presenter_graphs(self.fixture.records, replace(self.fixture.context, guard=mutate))


if __name__ == "__main__":
    unittest.main()
