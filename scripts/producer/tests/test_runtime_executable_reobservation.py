"""Contract tests for callback-lifetime runtime executable reobservation."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _runtime_executable_fixture import runtime_executable_fixture
from headless.runtime_executable_reobservation import (
    RuntimeExecutableReobservationError,
    reobserve_runtime_executables,
)
from headless.runtime_executable_reobservation_wire import (
    EXECUTABLE_REOBSERVATION_STATUS,
    RuntimeExecutableReobservationSchemaError,
    parse_runtime_executable_reobservation_report_v1,
    validate_runtime_executable_reobservation_report_v1,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


class _AlwaysEqualString(str):
    def __eq__(self, value: object) -> bool:
        return True


class _CallbackFailure(RuntimeError):
    pass


def _matching_descriptors(device: int, inode: int) -> tuple[int, ...]:
    matches = []
    for name in os.listdir("/dev/fd"):
        if not name.isdigit():
            continue
        try:
            info = os.fstat(int(name))
        except OSError:
            continue
        if (info.st_dev, info.st_ino) == (device, inode):
            matches.append(int(name))
    return tuple(matches)


class RuntimeExecutableReobservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = runtime_executable_fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_tools_are_held_rehashed_and_explicitly_non_authorizing(
        self,
    ) -> None:
        seen = []

        def observe(view: object) -> dict:
            seen.append(view)
            self.assertFalse(hasattr(view.ffmpeg, "fd"))
            self.assertTrue(
                _matching_descriptors(view.ffmpeg.device, view.ffmpeg.inode)
            )
            self.assertTrue(
                _matching_descriptors(view.ffprobe.device, view.ffprobe.inode)
            )
            return {"opaque": "callback-result"}

        outcome = reobserve_runtime_executables(self.fixture.request, observe)
        report = outcome.report
        self.assertEqual(
            outcome.observation_result, {"opaque": "callback-result"}
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(report.status, EXECUTABLE_REOBSERVATION_STATUS)
        self.assertEqual(report.scope, "synchronous-callback-endpoints")
        self.assertTrue(report.claims.callback_completed)
        self.assertTrue(report.claims.exact_executable_bytes_reobserved)
        self.assertTrue(report.claims.inode_snapshots_stable)
        self.assertFalse(report.claims.runtime_verified)
        self.assertFalse(report.claims.dynamic_library_closure_verified)
        self.assertFalse(report.claims.execution_reobserved)
        self.assertFalse(report.claims.process_execution_attested)
        self.assertFalse(report.claims.quality_measurements_reobserved)
        self.assertFalse(report.claims.execution_authorized)
        self.assertFalse(report.claims.publication_authorized)
        validate_runtime_executable_reobservation_report_v1(report)
        for snapshot in (report.ffmpeg, report.ffprobe):
            self.assertFalse(
                _matching_descriptors(snapshot.device, snapshot.inode),
                snapshot.path,
            )

    def test_report_is_bound_to_exact_manifest_request_policy_and_tool_roles(
        self,
    ) -> None:
        report = reobserve_runtime_executables(
            self.fixture.request, lambda view: None
        ).report
        manifest = self.fixture.request.runtime_manifest
        self.assertEqual(report.request_digest, manifest.request_digest)
        self.assertEqual(report.quality_policy_id, manifest.quality_policy_id)
        self.assertEqual(report.ffmpeg.sha256, manifest.ffmpeg.sha256)
        self.assertEqual(report.ffprobe.sha256, manifest.ffprobe.sha256)
        self.assertEqual(
            parse_runtime_executable_reobservation_report_v1(
                report.document_json
            ),
            report,
        )

    def test_callback_failure_is_preserved_after_successful_postcheck(
        self,
    ) -> None:
        def fail(_view: object) -> None:
            raise _CallbackFailure("callback failed")

        with self.assertRaisesRegex(_CallbackFailure, "callback failed"):
            reobserve_runtime_executables(self.fixture.request, fail)
        for path in (self.fixture.ffmpeg_path, self.fixture.ffprobe_path):
            info = os.stat(path)
            self.assertFalse(_matching_descriptors(info.st_dev, info.st_ino))

    def test_non_callable_and_role_alias_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            RuntimeExecutableReobservationError, "callback"
        ):
            reobserve_runtime_executables(self.fixture.request, None)
        alias = dataclasses.replace(
            self.fixture.request, ffprobe_path=self.fixture.ffmpeg_path
        )
        with self.assertRaisesRegex(
            RuntimeExecutableReobservationError, "roles alias"
        ):
            reobserve_runtime_executables(alias, lambda view: None)

    def test_forged_manifest_and_hostile_path_equality_are_rejected(
        self,
    ) -> None:
        manifest = self.fixture.request.runtime_manifest
        forged_tool = dataclasses.replace(
            manifest.ffmpeg, sha256=_AlwaysEqual()
        )
        forged_manifest = dataclasses.replace(manifest, ffmpeg=forged_tool)
        forged = dataclasses.replace(
            self.fixture.request, runtime_manifest=forged_manifest
        )
        hostile_path = dataclasses.replace(
            self.fixture.request,
            ffmpeg_path=_AlwaysEqualString(self.fixture.ffmpeg_path),
        )
        for request in (forged, hostile_path):
            with self.subTest(request=request), self.assertRaises(
                RuntimeExecutableReobservationError
            ):
                reobserve_runtime_executables(request, lambda view: None)

    def test_report_mutation_hostile_equality_and_overclaim_are_rejected(
        self,
    ) -> None:
        report = reobserve_runtime_executables(
            self.fixture.request, lambda view: None
        ).report
        forged_status = dataclasses.replace(report, status=_AlwaysEqual())
        forged_tool = dataclasses.replace(report.ffmpeg, sha256=_AlwaysEqual())
        forged_snapshot = dataclasses.replace(report, ffmpeg=forged_tool)
        for forged in (forged_status, forged_snapshot):
            with self.subTest(forged=forged), self.assertRaises(
                RuntimeExecutableReobservationSchemaError
            ):
                validate_runtime_executable_reobservation_report_v1(forged)
        document = json.loads(report.document_json)
        document["claims"]["publicationAuthorized"] = True
        with self.assertRaises(RuntimeExecutableReobservationSchemaError):
            parse_runtime_executable_reobservation_report_v1(
                canonical(document)
            )
        with self.assertRaises(RuntimeExecutableReobservationSchemaError):
            parse_runtime_executable_reobservation_report_v1(
                report.document_json + b"\n"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
