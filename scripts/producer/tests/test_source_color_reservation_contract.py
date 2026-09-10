"""Pure reservation plans survive partial publication without granting cleanup authority."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import UUID

from _source_color_staging_fixture import planned_job, staging_fixture
from guided_source_color_staging_contract import validate_source_color_reservation


class SourceColorReservationContractTests(unittest.TestCase):
    """Closed runtime, original references and complete ordered planned names only."""

    def setUp(self) -> None:
        """Allocate inert dictionaries only; no sidecar or source file is needed."""
        self.value = staging_fixture()[1]

    def reject(self) -> None:
        """Reject malformed metadata without granting repair or deletion authority."""
        with self.assertRaises((ValueError, TypeError)):
            validate_source_color_reservation(self.value)

    def test_detached_plans_preserve_order_without_sidecar_or_any_io(self) -> None:
        """A positive original PID remains inert metadata, even for another controller."""
        with patch("builtins.open", side_effect=AssertionError("no IO")), \
                patch("time.monotonic", side_effect=AssertionError("no clock")), \
                patch("subprocess.Popen", side_effect=AssertionError("no process")):
            actual = validate_source_color_reservation(self.value)
        self.assertEqual(actual, self.value)
        self.assertEqual([row["sourceId"] for row in actual["jobs"]], ["raw-b", "raw-a"])
        actual["jobs"].reverse()
        self.assertNotEqual(actual, self.value)

    def test_closed_schema_scope_and_authority_looking_fields_reject(self) -> None:
        """No bool pseudo-version or standalone cleanup-success field is supported."""
        for key, value in (("schemaVersion", True), ("schemaVersion", 1), ("scope", "cleanup-approved"),
                           ("cleanupVerified", True), ("executable", False)):
            self.value = staging_fixture()[1]
            self.value[key] = value
            self.reject()

    def test_pid_and_semantic_hash_have_strict_types(self) -> None:
        """Neither coercion nor a missing request hash can identify an original reservation."""
        for value in (True, 0, -1, "1234", 2 ** 31):
            self.value["ownerPid"] = value
            self.reject()
        for value in (None, "0" * 63, "A" * 64, False):
            self.value = staging_fixture()[1]
            self.value["sourceColorHash"] = value
            self.reject()

    def test_all_planned_names_are_required_unique_and_bounded(self) -> None:
        """A repeated source or UUID never aliases two jobs and empty means unsupported."""
        for jobs in ([], None, {}, self.value["jobs"] * 65):
            self.value = staging_fixture()[1]
            self.value["jobs"] = jobs
            self.reject()
        self.value = staging_fixture()[1]
        self.value["jobs"][1] = deepcopy(self.value["jobs"][0])
        self.reject()
        self.value = staging_fixture()[1]
        self.value["jobs"][1]["sourceId"] = self.value["jobs"][0]["sourceId"]
        self.reject()

    def test_planned_rows_cannot_contain_staged_or_unknown_payloads(self) -> None:
        """Raw job files and arbitrary commands are outside the reservation schema."""
        for key in ("input", "implementation", "launchClaim", "command"):
            self.value = staging_fixture()[1]
            self.value["jobs"][0][key] = {}
            self.reject()

    def test_exact_128_distinct_jobs_keep_their_original_order(self) -> None:
        """The full supported reservation fits without sorting, deduplication or IO."""
        self.value["jobs"] = [planned_job(self.value["producerDir"], f"raw-{index}", str(UUID(int=index + 1, version=4)))
                              for index in range(128)]
        result = validate_source_color_reservation(self.value)
        self.assertEqual(result["jobs"], self.value["jobs"])
        self.assertEqual(len(result["jobs"]), 128)

    def test_every_derived_job_path_and_container_name_is_exact(self) -> None:
        """Future paths are lexical only, with exact v4 IDs and no native inspection."""
        for key in ("directory", "inputPath", "implementationPath", "launchClaimPath", "executionDir", "containerName", "jobId"):
            self.value = staging_fixture()[1]
            self.value["jobs"][0][key] += "-other"
            self.reject()

    def test_opening_and_sidecar_paths_still_bind_original_execution(self) -> None:
        """Absent sidecar bytes do not permit a different prospective namespace."""
        for key in ("producerDir", "sidecarPath"):
            self.value = staging_fixture()[1]
            self.value[key] += "-other"
            self.reject()
        for key in ("claimPath", "inputPath", "executionId", "generationStartedAt", "claimSha256"):
            self.value = staging_fixture()[1]
            self.value["opening"][key] += "-other"
            self.reject()

    def test_runtime_shape_never_resolves_or_admits_actual_tools(self) -> None:
        """Unknown images, malformed raw references and numeric socket coercion reject."""
        for key, value in (("imageId", "latest"), ("dockerSha256", None), ("dockerSocketInode", 1),
                           ("dockerSocketDevice", "01"), ("userId", "0:0"), ("runtimeRepoRoot", "/TEST/../repo")):
            self.value = staging_fixture()[1]
            self.value["runtime"][key] = value
            self.reject()


if __name__ == "__main__":
    unittest.main()
