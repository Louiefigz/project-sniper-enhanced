"""Pure closed staging joins; TEST dictionaries never grant execution or raw-byte authority."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from _source_color_staging_fixture import staging_fixture
from cut_preview_io import digest
from guided_source_color_staging_contract import validate_source_color_staging


class SourceColorStagingContractTests(unittest.TestCase):
    """Validate exact all-source metadata and reject mutually edited transport shapes."""

    def setUp(self) -> None:
        """Allocate detached inert dictionaries, not files or owner objects."""
        self.sidecar, self.reservation = staging_fixture()

    def reject(self, pattern: str = "") -> None:
        """Require validation failure without interpreting it as cleanup or recovery."""
        with self.assertRaisesRegex((ValueError, TypeError), pattern):
            validate_source_color_staging(self.sidecar, self.reservation)

    def rehash_request(self) -> None:
        """Rehash only TEST request metadata to exercise semantic rejection underneath."""
        self.reservation["sourceColorHash"] = digest(self.sidecar["sourceColor"])

    def test_mixed_profiles_and_actual_reserved_order_are_retained_detached(self) -> None:
        """Dictionary insertion order does not override the actual reserved source order."""
        result = validate_source_color_staging(self.sidecar, self.reservation)
        self.assertEqual(result, self.sidecar)
        self.assertEqual([row["sourceId"] for row in result["jobs"]], ["raw-b", "raw-a"])
        self.assertIsNone(result["sourceColor"]["declarations"]["raw-a"]["profile"])
        self.assertIs(result["executable"], False)
        result["sourceColor"]["declarations"]["raw-a"]["declaration"]["cameraProfile"] = "TEST changed result"
        self.assertIsNone(self.sidecar["sourceColor"]["declarations"]["raw-a"]["declaration"]["cameraProfile"])
        self.assertNotIn("frameCount", result["jobs"][0])

    def test_no_file_process_or_clock_calls_are_needed(self) -> None:
        """Pure parsing succeeds even when reads, process starts and clocks are forbidden."""
        with patch("builtins.open", side_effect=AssertionError("no reads")), \
                patch("subprocess.Popen", side_effect=AssertionError("no process")), \
                patch("time.monotonic", side_effect=AssertionError("no timer")):
            validate_source_color_staging(self.sidecar, self.reservation)

    def test_raw_reservation_sha_is_not_recomputed_from_values(self) -> None:
        """Raw byte authentication belongs to the future held reader, not this value join."""
        self.sidecar["reservation"]["sha256"] = "9" * 64
        result = validate_source_color_staging(self.sidecar, self.reservation)
        self.assertEqual(result["reservation"]["sha256"], "9" * 64)

    def test_closed_top_level_and_runtime_fields(self) -> None:
        """Unknown authorization-looking fields cannot be retained as accepted metadata."""
        for name in ("sidecar", "reservation", "runtime"):
            self.sidecar, self.reservation = staging_fixture()
            target = self.sidecar if name == "sidecar" else self.reservation
            if name == "runtime":
                target = self.reservation["runtime"]
            target["qcPassed"] = True
            self.reject("missing or unknown")

    def test_bool_versions_and_numeric_false_flags_reject(self) -> None:
        """Python equality cannot launder true as1 or0 asfalse."""
        for field in ("schemaVersion", "executable", "gradeApplicable", "deliveryApproved"):
            self.sidecar, self.reservation = staging_fixture()
            self.sidecar[field] = True if field == "schemaVersion" else 0
            self.reject("flags differ")

    def test_reservation_role_and_owner_pid_are_closed(self) -> None:
        """An owner PID is mandatory metadata, never a live-process claim."""
        for value in (True, 0, -1, "1234", 2 ** 31):
            self.reservation["ownerPid"] = value
            self.reject("integer")
        self.reservation["ownerPid"] = 1234
        self.reservation["schemaVersion"] = 1
        self.reject("role")

    def test_all_opening_fields_must_match_both_documents(self) -> None:
        """A separately valid opening digest cannot silently substitute another parent."""
        for field in ("claimSha256", "inputSha256", "executionInputHash", "clockHash", "budgetAdmissionHash", "beforeJournalHash"):
            self.sidecar, self.reservation = staging_fixture()
            self.reservation["opening"][field] = "9" * 64
            self.reject("opening references differ")

    def test_claim_and_sidecar_paths_derive_from_the_original_execution(self) -> None:
        """No sibling execution or arbitrary future sidecar can be selected by JSON."""
        self.reservation["sidecarPath"] = self.reservation["sidecarPath"].replace("source-color/input", "other/input")
        self.reject("producer/sidecar")
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["opening"]["claimPath"] = self.sidecar["opening"]["claimPath"].replace("executions", "other")
        self.reject("claim path")

    def test_timestamp_spelling_and_real_calendar_date_are_validated(self) -> None:
        """No original clock is minted from a malformed or substituted timestamp."""
        for value in ("2026-09-08T00:00:00Z", "2026-02-30T00:00:00.000Z", True):
            self.sidecar["opening"]["generationStartedAt"] = value
            self.reject()

    def test_job_list_bounds_and_missing_all_source_coverage(self) -> None:
        """Partial jobs and repeated oversized arrays never satisfy complete coverage."""
        self.sidecar["jobs"] = []
        self.reject("job lists")
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["jobs"] *= 65
        self.reject("job lists")
        self.sidecar, self.reservation = staging_fixture()
        del self.sidecar["sourceColor"]["declarations"]["raw-a"]
        self.rehash_request()
        self.reject("coverage")

    def test_job_order_and_uuid_duplication_reject(self) -> None:
        """Original array order matters; exact plans are not sorted or deduplicated."""
        self.reservation["jobs"].reverse()
        self.reject("order")
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["jobs"][1] = deepcopy(self.sidecar["jobs"][0])
        self.reservation["jobs"][1] = deepcopy(self.reservation["jobs"][0])
        self.reject("coverage/job order")

    def test_non_v4_job_and_noncanonical_paths_reject(self) -> None:
        """Paths are checked lexically with no resolve/stat or directory creation."""
        self.sidecar["jobs"][0]["jobId"] = "79c7d2a8-f1ae-1c74-8bfc-6b959b888211"
        self.reject("UUID")
        for value in ("relative/input.json", "/TEST/../input.json", "/TEST//input.json", "/TEST\\input.json"):
            self.sidecar, self.reservation = staging_fixture()
            self.sidecar["jobs"][0]["inputPath"] = value
            self.reject("canonical")

    def test_every_prospective_path_and_raw_reference_must_match(self) -> None:
        """Input, implementation and launch bytes cannot point to a different job."""
        for field in ("directory", "inputPath", "implementationPath", "launchClaimPath", "executionDir", "containerName"):
            self.sidecar, self.reservation = staging_fixture()
            self.sidecar["jobs"][0][field] += "-other"
            self.reject("path/container")
        for field in ("input", "implementation", "launchClaim"):
            self.sidecar, self.reservation = staging_fixture()
            self.sidecar["jobs"][0][field]["path"] += "-other"
            self.reject("reference path")

    def test_raw_ref_and_parent_sha_types_are_strict(self) -> None:
        """A null SHA cannot disable a future reader's separately held raw hash."""
        for value in (True, 0, "200", 8 * 1024 ** 2 + 1):
            self.sidecar["reservation"]["sizeBytes"] = value
            self.reject("integer")
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["expected"]["planSha256"] = None
        self.reject("SHA")

    def test_runtime_types_and_unknown_image_user_are_rejected(self) -> None:
        """Shape checking does not follow a socket or discover an executable."""
        for field, value in (("dockerSocketDevice", 1), ("dockerSocketInode", "01"), ("dockerSha256", None),
                             ("imageId", "latest"), ("userId", "0:0"), ("runtimeRepoRoot", "/TEST/../repo")):
            self.sidecar, self.reservation = staging_fixture()
            self.reservation["runtime"][field] = value
            self.reject()

    def test_explicit_profile_and_declared_history_cannot_be_filled(self) -> None:
        """Missing profile is not legacy and unknown V1 history is not known history."""
        del self.sidecar["sourceColor"]["declarations"]["raw-a"]["profile"]
        self.reject("selection")
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["sourceColor"]["declarations"]["raw-a"]["declaration"]["historyState"] = "unknown"
        self.rehash_request()
        self.reject("profile/history")

    def test_rehashed_declared_group_gap_boolean_and_overflow_reject(self) -> None:
        """Declared ranges remain strict and bounded without asserting actual EOF."""
        for field, value in (("startFrame", 1), ("startFrame", False), ("endFrame", 24001), ("intent", True)):
            self.sidecar, self.reservation = staging_fixture()
            self.sidecar["sourceColor"]["declarations"]["raw-b"]["declaration"]["lightingGroups"][0][field] = value
            self.rehash_request()
            self.reject()

    def test_changed_unicode_request_requires_exact_semantic_hash(self) -> None:
        """Real Unicode prose stays literal and participates in the shared digest domain."""
        self.sidecar["sourceColor"]["declarations"]["raw-a"]["declaration"]["cameraProfile"] = "TEST caméra 🎥"
        self.reject("semantic request hash")
        self.rehash_request()
        self.assertEqual(validate_source_color_staging(self.sidecar, self.reservation), self.sidecar)


if __name__ == "__main__":
    unittest.main()
