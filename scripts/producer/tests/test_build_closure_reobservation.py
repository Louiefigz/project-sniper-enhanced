"""Adversarial source/tool build-closure reobservation tests."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _build_closure_reobservation_fixture import build_closure_fixture
from headless.build_closure_reobservation import (
    BuildClosureReobservationError,
    require_build_closure_execution_authorized,
    reobserve_build_closure,
)
from headless.build_closure_reobservation_wire import (
    BUILD_CLOSURE_REOBSERVATION_STATUS,
    BuildClosureReobservationSchemaError,
    parse_build_closure_reobservation_report_v1,
    validate_build_closure_reobservation_report_v1,
)
from headless.compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
)
from headless.render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


class _CallbackFailure(RuntimeError):
    pass


class BuildClosureReobservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = build_closure_fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_declared_sources_and_tools_reobserve_without_authority(
        self,
    ) -> None:
        outcome = reobserve_build_closure(
            self.fixture.request,
            lambda view: (view.source_count, view.tool_count),
        )
        report = outcome.report
        expected = len(COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS) + len(
            RENDER_BUILD_V1_IMPLEMENTATION_PATHS
        )
        self.assertEqual(outcome.observation_result, (expected, 4))
        self.assertEqual(report.status, BUILD_CLOSURE_REOBSERVATION_STATUS)
        self.assertEqual(
            (report.sources.count, report.tools.count), (expected, 4)
        )
        self.assertTrue(report.claims.exact_source_bytes_reobserved)
        self.assertTrue(report.claims.exact_tool_bytes_reobserved)
        self.assertTrue(report.claims.source_root_descriptor_held)
        self.assertTrue(report.claims.tool_inode_descriptors_held)
        self.assertFalse(report.claims.runtime_verified)
        self.assertFalse(report.claims.execution_reobserved)
        self.assertFalse(report.claims.execution_authorized)
        self.assertFalse(report.claims.publication_authorized)
        self.assertNotIn(self.root.encode("utf-8"), report.document_json)
        validate_build_closure_reobservation_report_v1(report)
        with self.assertRaisesRegex(
            BuildClosureReobservationError, BUILD_CLOSURE_REOBSERVATION_STATUS
        ):
            require_build_closure_execution_authorized(report)

    def test_source_mutation_before_or_during_callback_rejects(self) -> None:
        before = self.fixture.sources[0]
        with open(before, "ab") as handle:
            handle.write(b"mutation")
        with self.assertRaises(BuildClosureReobservationError):
            reobserve_build_closure(self.fixture.request, lambda view: None)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = build_closure_fixture(self.root)

        def mutate(_view: object) -> None:
            with open(self.fixture.sources[1], "ab") as handle:
                handle.write(b"mutation")

        with self.assertRaises(BuildClosureReobservationError):
            reobserve_build_closure(self.fixture.request, mutate)

    def test_identical_source_inode_replacement_is_detected(self) -> None:
        target = self.fixture.sources[2]
        with open(target, "rb") as handle:
            raw = handle.read()
        replacement = os.path.join(self.root, "replacement-source")
        with open(replacement, "wb") as handle:
            handle.write(raw)

        def replace(_view: object) -> None:
            os.replace(replacement, target)

        with self.assertRaises(BuildClosureReobservationError):
            reobserve_build_closure(self.fixture.request, replace)

    def test_tool_mutation_and_identical_inode_replacement_reject(
        self,
    ) -> None:
        for case in ("mutate", "replace"):
            with self.subTest(case=case):
                self.temporary.cleanup()
                self.temporary = tempfile.TemporaryDirectory()
                self.root = os.path.realpath(self.temporary.name)
                self.fixture = build_closure_fixture(self.root)
                target = self.fixture.tools[1]

                def attack(_view: object) -> None:
                    if case == "mutate":
                        with open(target, "ab") as handle:
                            handle.write(b"mutation")
                        return
                    replacement = os.path.join(self.root, "replacement-tool")
                    with open(target, "rb") as handle:
                        raw = handle.read()
                    with open(replacement, "wb") as handle:
                        handle.write(raw)
                    os.chmod(replacement, 0o700)
                    os.replace(replacement, target)

                with self.assertRaises(BuildClosureReobservationError):
                    reobserve_build_closure(self.fixture.request, attack)

    def test_source_symlink_hardlink_and_tool_hardlink_reject(self) -> None:
        source = self.fixture.sources[0]
        displaced = source + ".real"
        os.rename(source, displaced)
        os.symlink(displaced, source)
        with self.assertRaises((BuildClosureReobservationError, RuntimeError)):
            reobserve_build_closure(self.fixture.request, lambda view: None)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = build_closure_fixture(self.root)
        os.link(
            self.fixture.tools[0], os.path.join(self.root, "tool-hardlink")
        )
        with self.assertRaises(BuildClosureReobservationError):
            reobserve_build_closure(self.fixture.request, lambda view: None)

    def test_source_hardlink_and_group_writable_mode_reject(self) -> None:
        for case in ("hardlink", "writable"):
            with self.subTest(case=case):
                self.temporary.cleanup()
                self.temporary = tempfile.TemporaryDirectory()
                self.root = os.path.realpath(self.temporary.name)
                self.fixture = build_closure_fixture(self.root)
                source = self.fixture.sources[0]
                if case == "hardlink":
                    os.link(source, os.path.join(self.root, "source-hardlink"))
                else:
                    os.chmod(source, 0o620)
                with self.assertRaises(BuildClosureReobservationError):
                    reobserve_build_closure(
                        self.fixture.request, lambda view: None
                    )

    def test_failed_callback_still_runs_postchecks(self) -> None:
        def mutate_and_fail(_view: object) -> None:
            with open(self.fixture.sources[3], "ab") as handle:
                handle.write(b"mutation")
            raise _CallbackFailure("callback failed")

        with self.assertRaisesRegex(
            BuildClosureReobservationError, "failed observation"
        ):
            reobserve_build_closure(self.fixture.request, mutate_and_fail)

    def test_invalid_request_callback_and_forged_binding_reject(self) -> None:
        binding = self.fixture.request.binding
        compositor = dataclasses.replace(
            binding.compositor_receipt, build_digest=_AlwaysEqual()
        )
        forged = dataclasses.replace(
            self.fixture.request,
            binding=dataclasses.replace(
                binding, compositor_receipt=compositor
            ),
        )
        cases = ((object(), lambda view: None), (forged, lambda view: None))
        for request, callback in cases:
            with self.subTest(request=request), self.assertRaises(
                BuildClosureReobservationError
            ):
                reobserve_build_closure(request, callback)
        with self.assertRaises(BuildClosureReobservationError):
            reobserve_build_closure(self.fixture.request, None)

    def test_report_overclaim_noncanonical_and_hostile_equality_reject(
        self,
    ) -> None:
        report = reobserve_build_closure(
            self.fixture.request, lambda view: None
        ).report
        forged = dataclasses.replace(report, status=_AlwaysEqual())
        with self.assertRaises(BuildClosureReobservationSchemaError):
            validate_build_closure_reobservation_report_v1(forged)
        document = json.loads(report.document_json)
        document["claims"]["executionAuthorized"] = True
        with self.assertRaises(BuildClosureReobservationSchemaError):
            parse_build_closure_reobservation_report_v1(canonical(document))
        with self.assertRaises(BuildClosureReobservationSchemaError):
            parse_build_closure_reobservation_report_v1(
                report.document_json + b"\n"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
