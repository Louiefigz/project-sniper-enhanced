"""Filesystem adversaries for held runtime executable reobservation."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _runtime_executable_fixture import (
    FFMPEG_BYTES,
    FFPROBE_BYTES,
    digest,
    runtime_executable_fixture,
    write_executable,
)
from headless.runtime_capability_manifest import (
    parse_runtime_capability_manifest_v1,
)
from headless.runtime_executable_reobservation import (
    RuntimeExecutableReobservationError,
    reobserve_runtime_executables,
)


class _CallbackFailure(RuntimeError):
    pass


class RuntimeExecutableReobservationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = runtime_executable_fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assertRejected(self, callback) -> None:  # noqa: N802
        with self.assertRaises(RuntimeExecutableReobservationError):
            reobserve_runtime_executables(self.fixture.request, callback)

    def test_in_place_byte_mutation_is_detected_after_callback(self) -> None:
        def mutate(_view: object) -> None:
            with open(self.fixture.ffmpeg_path, "wb") as handle:
                handle.write(b"mutated-ffmpeg-executable\n")

        self.assertRejected(mutate)

    def test_identical_byte_inode_replacement_is_detected(self) -> None:
        replacement = os.path.join(self.root, "replacement-ffmpeg")
        write_executable(replacement, FFMPEG_BYTES)

        def replace(_view: object) -> None:
            os.replace(replacement, self.fixture.ffmpeg_path)

        self.assertRejected(replace)

    def test_symlink_replacement_is_detected(self) -> None:
        replacement = os.path.join(self.root, "symlink-target")
        write_executable(replacement, FFMPEG_BYTES)

        def replace(_view: object) -> None:
            os.unlink(self.fixture.ffmpeg_path)
            os.symlink(replacement, self.fixture.ffmpeg_path)

        self.assertRejected(replace)

    def test_parent_directory_replacement_is_detected(self) -> None:
        tool_root = os.path.dirname(self.fixture.ffmpeg_path)
        displaced = os.path.join(self.root, "displaced-tools")

        def replace(_view: object) -> None:
            os.rename(tool_root, displaced)
            os.mkdir(tool_root, 0o700)
            write_executable(os.path.join(tool_root, "ffmpeg"), FFMPEG_BYTES)
            write_executable(os.path.join(tool_root, "ffprobe"), FFPROBE_BYTES)

        self.assertRejected(replace)

    def test_unrelated_child_directory_does_not_change_path_binding(
        self,
    ) -> None:
        tool_root = os.path.dirname(self.fixture.ffmpeg_path)
        unrelated = os.path.join(tool_root, "unrelated-child")

        def create_unrelated(_view: object) -> None:
            os.mkdir(unrelated, 0o700)

        outcome = reobserve_runtime_executables(
            self.fixture.request, create_unrelated
        )
        self.assertIsNone(outcome.observation_result)

    def test_parent_directory_mode_mutation_is_detected(self) -> None:
        tool_root = os.path.dirname(self.fixture.ffmpeg_path)

        def mutate(_view: object) -> None:
            os.chmod(tool_root, 0o500)

        self.assertRejected(mutate)

    def test_mutation_during_failed_callback_still_runs_postcheck(
        self,
    ) -> None:
        def mutate_and_fail(_view: object) -> None:
            os.chmod(self.fixture.ffprobe_path, 0o500)
            raise _CallbackFailure("original callback failure")

        with self.assertRaisesRegex(
            RuntimeExecutableReobservationError, "failed observation"
        ):
            reobserve_runtime_executables(
                self.fixture.request, mutate_and_fail
            )

    def test_leaf_and_parent_symlinks_are_rejected_before_callback(
        self,
    ) -> None:
        target = os.path.join(self.root, "target")
        write_executable(target, FFMPEG_BYTES)
        leaf = os.path.join(self.root, "ffmpeg-link")
        os.symlink(target, leaf)
        leaf_request = dataclasses.replace(
            self.fixture.request, ffmpeg_path=leaf
        )
        real_tools = os.path.dirname(self.fixture.ffprobe_path)
        parent_link = os.path.join(self.root, "tools-link")
        os.symlink(real_tools, parent_link)
        parent_request = dataclasses.replace(
            self.fixture.request,
            ffprobe_path=os.path.join(parent_link, "ffprobe"),
        )
        for request in (leaf_request, parent_request):
            with self.subTest(request=request), self.assertRaises(
                RuntimeExecutableReobservationError
            ):
                reobserve_runtime_executables(request, lambda view: None)

    def test_noncanonical_swapped_and_wrong_declared_paths_are_rejected(
        self,
    ) -> None:
        noncanonical = dataclasses.replace(
            self.fixture.request,
            ffmpeg_path=os.path.join(
                os.path.dirname(self.fixture.ffmpeg_path), ".", "ffmpeg"
            ),
        )
        swapped = dataclasses.replace(
            self.fixture.request,
            ffmpeg_path=self.fixture.ffprobe_path,
            ffprobe_path=self.fixture.ffmpeg_path,
        )
        missing = dataclasses.replace(
            self.fixture.request,
            ffprobe_path=os.path.join(self.root, "missing"),
        )
        for request in (noncanonical, swapped, missing):
            with self.subTest(request=request), self.assertRaises(
                RuntimeExecutableReobservationError
            ):
                reobserve_runtime_executables(request, lambda view: None)

    def test_digest_mismatch_is_rejected_before_callback(self) -> None:
        manifest = self.fixture.request.runtime_manifest
        document = json.loads(manifest.document_json)
        document["tools"]["ffmpeg"]["sha256"] = digest(b"different-tool")
        changed = parse_runtime_capability_manifest_v1(canonical(document))
        request = dataclasses.replace(
            self.fixture.request, runtime_manifest=changed
        )
        called = []
        with self.assertRaisesRegex(
            RuntimeExecutableReobservationError, "runtime declaration"
        ):
            reobserve_runtime_executables(
                request, lambda view: called.append(view)
            )
        self.assertEqual(called, [])

    def test_hardlinks_and_group_writable_executables_are_rejected(
        self,
    ) -> None:
        hardlink = os.path.join(self.root, "hardlink")
        os.link(self.fixture.ffmpeg_path, hardlink)
        with self.assertRaises(RuntimeExecutableReobservationError):
            reobserve_runtime_executables(
                self.fixture.request, lambda view: None
            )
        os.unlink(hardlink)
        os.chmod(self.fixture.ffmpeg_path, 0o720)
        with self.assertRaises(RuntimeExecutableReobservationError):
            reobserve_runtime_executables(
                self.fixture.request, lambda view: None
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
