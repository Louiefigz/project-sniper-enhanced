"""Actual live observation projection; native/admission leaves remain TEST-only."""
from __future__ import annotations

from unittest.mock import patch
import unittest

from _source_color_base_context_fixture import SourceOnlyBaseFixture
from _source_color_batch_fixture import SourceColorBatchFixture, current_batch_test_pins
from cut_preview_io import digest
import guided_source_color_observation_projection as projection


class SourceColorObservationProjectionTests(unittest.TestCase):
    """No JSON data is substituted for the actual same-process holder chain."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture current implementation once during an explicitly stable cohort."""
        cls.pins = current_batch_test_pins()

    def fixture(self) -> tuple:
        """Retain only this fixture's original exact owned TEST paths for mutations."""
        fixture = SourceOnlyBaseFixture(self.pins)
        self.addCleanup(fixture.cleanup)
        return fixture, fixture.base_context(fixture.identity())

    def test_real_ordered_projection_reuses_original_raw_refs_and_false_flags(self) -> None:
        """Existing metadata is projected once without a new source/native invocation."""
        fixture, context = self.fixture()
        calls = len(fixture.calls)
        result = projection.project_source_color_observations(context)
        self.assertEqual(len(fixture.calls), calls)
        self.assertEqual(result["processInput"]["input"]["sha256"], fixture.reference[1])
        self.assertEqual(result["processInput"]["sourceColorHash"], digest(fixture.sidecar["sourceColor"]))
        self.assertEqual([row["sourceId"] for row in result["sources"]], [row.source_id for row in fixture.refs])
        self.assertEqual(result["opening"], fixture.sidecar["opening"])
        self.assertEqual(result["parents"], fixture.sidecar["expected"])
        for projected, staged in zip(result["sources"], fixture.sidecar["jobs"]):
            self.assertEqual(projected["artifacts"]["implementation"], staged["implementation"])
            self.assertEqual(projected["artifacts"]["launchClaim"], staged["launchClaim"])
            self.assertEqual(projected["bt709Identity"]["decoded_frame_count"], projected["records"]["decodedFrames"])
        for flag in ("gamutMeasured", "gradeApplied", "basePictureObserved", "openingApproved", "deliveryApproved"):
            self.assertIs(result[flag], False)

    def test_projection_does_not_reopen_metadata_or_sources(self) -> None:
        """Original held bytes supply refs; their in-memory SHA computation is not waived."""
        fixture, context = self.fixture()
        with patch("cut_preview_io.read_bytes", side_effect=AssertionError("TEST unexpected bytes")), \
                patch("guided_source_color_staging_files.read_bytes", side_effect=AssertionError("TEST unexpected bytes")), \
                patch("color.grade_bt709_identity_read.read_bytes", side_effect=AssertionError("TEST unexpected bytes")):
            value = projection.project_source_color_observations(context)
        self.assertEqual(len(value["sources"]), 2)
        self.assertEqual(len(fixture.calls), 2)

    def test_return_is_detached_not_a_mutable_alias_to_original_declaration(self) -> None:
        """Editing a data-only projection neither updates the owner nor grants new work."""
        fixture, context = self.fixture()
        result = projection.project_source_color_observations(context)
        result["sources"][0]["selection"]["declaration"]["historyState"] = "unknown"
        context.assert_current()
        self.assertEqual(fixture.sidecar["sourceColor"]["declarations"][fixture.refs[0].source_id]["declaration"]["historyState"], "known")

    def test_original_preclaim_change_cannot_be_rebaselined_into_new_projection(self) -> None:
        """A new data projector must reject changed metadata held before native work."""
        fixture, context = self.fixture()
        SourceColorBatchFixture.change(fixture, fixture.refs[0].launch.claim_path, {"TEST": "changed after original observation"})
        self.assertRaises(RuntimeError, projection.project_source_color_observations, context)

    def test_retired_marker_is_not_a_new_live_projection_authority(self) -> None:
        """Cold receipt readers must use archived proof, not renew this live helper."""
        fixture, context = self.fixture()
        SourceColorBatchFixture.change(fixture, fixture.reservation_path, {"TEST": "retired reservation"})
        context.assert_current()
        self.assertRaises(RuntimeError, projection.project_source_color_observations, context)

    def test_dto_and_original_clock_expiry_refuse(self) -> None:
        """Serialized data does not instantiate a holder or create another deadline."""
        self.assertRaises(RuntimeError, projection.project_source_color_observations, {})
        fixture, context = self.fixture()
        fixture.now = fixture.clock.end
        self.assertRaises(RuntimeError, projection.project_source_color_observations, context)

    def test_final_callback_cannot_mutate_original_input_after_projection(self) -> None:
        """A complete local data object is not returned after original input changes."""
        fixture, context = self.fixture()
        original = projection._source_rows
        def projected(*args: object) -> list:
            """Install an in-memory TEST mutation only after all rows are built."""
            result = original(*args)
            fixture.guard.side_effect = lambda: fixture.inputs.documents["candidatePlan"].update(TEST="changed")
            return result
        with patch.object(projection, "_source_rows", side_effect=projected):
            self.assertRaises(RuntimeError, projection.project_source_color_observations, context)


if __name__ == "__main__":
    unittest.main()
