"""Pure synthetic contract cases, explicitly not authenticated source or frame proof."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _source_color_observation_contract_fixture import ObservationContractFixture
from _source_color_staging_fixture import selection
from cut_preview_io import digest
from guided_source_color_observation_contract import validate_source_color_observations


class SourceColorObservationContractTests(unittest.TestCase):
    """Original metadata joins stay separate from future IO and actual decoder replay."""

    def setUp(self) -> None:
        """Construct fabricated dictionaries only; no temporary files are necessary."""
        self.fixture = ObservationContractFixture()

    def validate(self) -> dict:
        """Call the actual pure validator, never a live-owner or frame-reader stub."""
        value = self.fixture
        return validate_source_color_observations(value.section, value.sidecar, value.reservation, value.inputs)

    def reject(self) -> None:
        """Invalid supplied metadata must not escape as a validated data section."""
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate()

    def test_data_only_positive_preserves_exact_shape_and_false_scope(self) -> None:
        """The return is detached JSON, not a capability, receipt publication or approval."""
        value = self.validate()
        self.assertEqual(value, self.fixture.section)
        self.assertIsNot(value, self.fixture.section)
        self.assertEqual([row["sourceId"] for row in value["sources"]], ["raw-b", "raw-a"])
        self.assertFalse(value["gamutMeasured"] or value["gradeApplied"] or value["basePictureObserved"])
        self.assertFalse(hasattr(value, "assert_current"))
        value["sources"][0]["selection"]["declaration"]["historyState"] = "unknown"
        self.validate()

    def test_no_files_processes_or_clocks_are_consulted(self) -> None:
        """Even impossible TEST paths work because this phase validates supplied metadata only."""
        with patch("builtins.open", side_effect=AssertionError("no IO")), \
                patch("os.open", side_effect=AssertionError("no IO")), \
                patch("subprocess.run", side_effect=AssertionError("no native")), \
                patch("time.monotonic", side_effect=AssertionError("no clock")):
            self.validate()

    def test_unknown_fields_and_false_flag_coercions_reject(self) -> None:
        """Closed roles never ignore extra authority fields or accept numeric false."""
        for key, value in (("extra", False), ("schemaVersion", True), ("openingApproved", 0),
                           ("gradeApplied", True), ("scope", "approved")):
            self.fixture = ObservationContractFixture()
            self.fixture.section[key] = value
            self.reject()

    def test_all_nested_contracts_reject_unknown_fields(self) -> None:
        """No unvalidated field can acquire meaning in a later durable receipt."""
        for name in ("source", "binding", "artifacts", "records", "bt709Identity", "timing", "selection"):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0][name]["extra"] = "TEST"
            self.reject()

    def test_missing_repeated_reordered_or_extra_sources_reject(self) -> None:
        """Exact first occurrence, not declaration-map ordering or set equality, controls rows."""
        for indices in ((0,), (0, 0), (1, 0), (0, 1, 0)):
            self.fixture = ObservationContractFixture()
            rows = self.fixture.section["sources"]
            self.fixture.section["sources"] = [deepcopy(rows[index]) for index in indices]
            self.reject()

    def test_reordered_staging_cannot_change_original_first_use(self) -> None:
        """A consistently reordered sidecar/reservation/section still differs from original cuts."""
        self.fixture.sidecar["jobs"].reverse()
        self.fixture.reservation["jobs"].reverse()
        self.fixture.section["sources"].reverse()
        self.reject()

    def test_job_id_and_staged_raw_refs_must_match(self) -> None:
        """Valid-looking foreign job hashes cannot replace original staged metadata."""
        for key in ("input", "implementation", "launchClaim"):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["artifacts"][key]["sha256"] = "f" * 64
            self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.section["sources"][0]["jobId"] = self.fixture.section["sources"][1]["jobId"]
        self.reject()

    def test_artifact_namespace_and_per_role_byte_caps_reject(self) -> None:
        """Frame metadata's larger cap cannot be borrowed by the small probe or preclaim."""
        for role, size in (("probe", 65537), ("frames", 128 * 1024 ** 2 + 1), ("launchClaim", 131073)):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["artifacts"][role]["sizeBytes"] = size
            self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.section["sources"][0]["artifacts"]["observation"]["path"] += "/../other"
        self.reject()

    def test_source_and_admission_hashes_are_joined_not_format_only(self) -> None:
        """A different well-formed SHA fails against actual original metadata slots."""
        for key in ("sourceSha256", "admissionReceiptSha256", "declarationSha256"):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["binding"][key] = "f" * 64
            self.reject()

    def test_source_size_cannot_be_coerced_or_changed(self) -> None:
        """Source byte identity uses exact integers from original capture and manifest."""
        for size in (4096.0, True, 4097):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["source"]["sizeBytes"] = size
            self.reject()

    def test_original_capture_or_manifest_substitution_rejects(self) -> None:
        """Current supplied source metadata must agree with its initial hash-pass projection."""
        capture = self.fixture.inputs.verified_media
        changed = replace(capture.snapshots[0], sha256="f" * 64)
        self.fixture.inputs = replace(self.fixture.inputs, verified_media=replace(capture, snapshots=(changed, capture.snapshots[1])))
        self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.manifest["sources"][0]["sourceSizeBytes"] = 4097
        self.reject()

    def test_known_v1_declaration_cannot_be_replaced_by_unknown_history(self) -> None:
        """No implicit camera/history or V2 profile choice is made by the contract."""
        selected = self.fixture.sidecar["sourceColor"]["declarations"]["raw-b"]
        selected["declaration"]["historyState"] = "unknown"
        self.fixture.reservation["sourceColorHash"] = digest(self.fixture.sidecar["sourceColor"])
        self.fixture.section["sources"][0]["selection"] = deepcopy(selected)
        self.reject()

    def test_consistent_v2_transport_cannot_be_relabelled_as_v1_identity(self) -> None:
        """A valid V2 staging choice still has no meaning as this known-BT709 section."""
        selected = selection("raw-b", True)
        self.fixture.sidecar["sourceColor"]["declarations"]["raw-b"] = selected
        sha = digest(self.fixture.sidecar["sourceColor"])
        self.fixture.reservation["sourceColorHash"] = sha
        self.fixture.section["processInput"]["sourceColorHash"] = sha
        self.fixture.section["sources"][0]["selection"] = deepcopy(selected)
        self.fixture.section["sources"][0]["binding"]["declarationSha256"] = digest(selected["declaration"])
        self.reject()

    def test_declared_frame_groups_must_match_record_binding(self) -> None:
        """Group coverage and reported count must agree, though admission replay remains pending."""
        row = self.fixture.section["sources"][0]
        row["binding"]["frameCount"] = 47
        row["records"]["decodedFrames"] = 47
        row["bt709Identity"]["decoded_frame_count"] = 47
        self.reject()

    def test_exact_rate_timebase_and_cadence_are_required(self) -> None:
        """No floating clock conversion, nonreduced token or rounded tick admission."""
        for changes in ({"timeBase": "2/48000"}, {"timeBase": 0.001}, {"stepTicks": 1000.0},
                        {"stepTicks": 999}, {"decodedFrames": 48.0}, {"width": 32.0}, {"firstPts": False}):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["records"].update(changes)
            self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.section["sources"][0]["binding"]["fps"] = "24/1"
        self.reject()

    def test_supplemental_identity_is_closed_square_known_and_nonapproving(self) -> None:
        """Missing chroma, rotation claims, other codecs and fabricated pixel proof reject."""
        for changes in ({"sample_aspect_ratio": "2:1"}, {"chroma_location": "unknown"}, {"codec": "hevc"},
                        {"pixel_orientation_measured": True}, {"decoded_frame_count": 48.0}, {"rotation_observation": "measured"}):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][0]["bt709Identity"].update(changes)
            self.reject()

    def test_timing_overlap_expansion_and_type_changes_reject(self) -> None:
        """Reported rounded milliseconds stay bounded and chronologically sequential."""
        for changes in ({"startedMs": 98}, {"elapsedMs": 102}, {"elapsedMs": 100.0}, {"cleanupVerified": 1}):
            self.fixture = ObservationContractFixture()
            self.fixture.section["sources"][1]["timing"].update(changes)
            self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.section["elapsedMs"] = 1_500_001
        self.reject()

    def test_intrinsic_millisecond_rounding_is_not_a_new_clock(self) -> None:
        """Only the producer's independently rounded one-millisecond discrepancy is allowed."""
        self.fixture.section["sources"][1]["timing"]["startedMs"] = 99
        self.validate()

    def test_look_presenter_and_reframe_are_not_stripped_or_relabeled(self) -> None:
        """Even an empty supplied presenter field or non-null default look remains unsupported."""
        for changes in ({"baselineLook": {}}, {"presenterLayouts": []}, {"reframe": {"strategy": "manual"}},
                        {"target": {"mode": "short"}}):
            self.fixture = ObservationContractFixture()
            self.fixture.inputs.documents["candidatePlan"].update(changes)
            self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.inputs.documents["candidatePlan"]["baselineLook"] = None
        self.validate()

    def test_original_accepted_controls_cannot_be_omitted_from_candidate(self) -> None:
        """A candidate without a control does not erase the unsupported original intent."""
        for changes in ({"baselineLook": {}}, {"presenterLayouts": []}, {"reframe": {"strategy": "manual"}}):
            self.fixture = ObservationContractFixture()
            self.fixture.inputs.documents["acceptedPlan"].update(changes)
            self.reject()

    def test_original_input_and_clock_lineage_cannot_be_substituted(self) -> None:
        """A self-consistent section cannot change the independent original input identity."""
        self.fixture.inputs = replace(self.fixture.inputs, sha256="f" * 64)
        self.reject()
        self.fixture = ObservationContractFixture()
        self.fixture.inputs.documents["authority"]["clockHash"] = "f" * 64
        self.reject()

    def test_unavailable_history_is_not_claimed_as_recomputed(self) -> None:
        """Only shape can be checked without original project.json; future replay must join it."""
        self.fixture.section["sources"][0]["binding"]["projectHistorySha256"] = "f" * 64
        value = self.validate()
        self.assertEqual(value["sources"][0]["binding"]["projectHistorySha256"], "f" * 64)
        self.assertNotIn("historyVerified", value)

    def test_admission_frame_count_is_unverified_until_original_receipt_replay(self) -> None:
        """Consistent declared counts cannot prove unavailable ingest frame facts."""
        selected = self.fixture.sidecar["sourceColor"]["declarations"]["raw-b"]
        selected["declaration"]["lightingGroups"][0]["endFrame"] = 50
        sha = digest(self.fixture.sidecar["sourceColor"])
        self.fixture.reservation["sourceColorHash"] = sha
        self.fixture.section["processInput"]["sourceColorHash"] = sha
        row = self.fixture.section["sources"][0]
        row["selection"] = deepcopy(selected)
        row["binding"].update(frameCount=50, declarationSha256=digest(selected["declaration"]))
        row["records"]["decodedFrames"] = 50
        row["bt709Identity"]["decoded_frame_count"] = 50
        value = self.validate()
        self.assertNotIn("admissionFramesVerified", value)

    def test_recorded_raw_hashes_remain_assertions_until_io_replay(self) -> None:
        """This pure return must never be relabeled as evidence of actual original decoder work."""
        self.fixture.section["sources"][0]["records"]["sha256"] = "f" * 64
        self.fixture.section["sources"][0]["artifacts"]["frames"]["sha256"] = "e" * 64
        value = self.validate()
        self.assertNotIn("decoderExecutionProved", value)
        self.assertFalse(value["gradeApplied"])


if __name__ == "__main__":
    unittest.main()
