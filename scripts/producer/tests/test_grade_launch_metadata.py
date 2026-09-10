"""Data-only batch preflight prerequisites; no source admission or execution.

Real tiny metadata files use the existing fixture's explicit socket-type TEST
stub. The prospective execution directory is absent during every metadata read.
No guard ownership, timer, source decode, record write or launch is synthesized.
"""
from __future__ import annotations

import os
import signal
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from _grade_launch_fixture import GradeLaunchFixture
from headless import grade_launch_intent as intent


class GradeLaunchMetadataTests(unittest.TestCase):
    """A reusable data projection must not become an execution handle."""

    def setUp(self) -> None:
        """Remove only the freshly created, exact empty TEST execution directory."""
        self.fixture = GradeLaunchFixture()
        self.addCleanup(self.fixture.close)
        path = self.fixture.directory
        self.assertEqual(path.resolve(strict=True), path)
        self.assertTrue(path.is_relative_to(self.fixture.root))
        self.assertEqual(tuple(path.iterdir()), ())
        path.rmdir()

    def read(self) -> tuple:
        """Invoke only the shared production metadata reader."""
        fixture = self.fixture
        return intent.read_grade_launch_metadata(fixture.owner, str(fixture.source), fixture.request, fixture.directory)

    def test_absent_execution_returns_only_original_data_and_raw_refs(self) -> None:
        """Keep exact claim/raw-parent/snapshot evidence without making resources."""
        fixture = self.fixture
        with patch.object(intent, "HeldGradeLaunch") as live, \
                patch.object(intent, "publish_launch_file") as write, patch.object(Path, "mkdir") as mkdir, \
                patch.object(signal, "setitimer") as timer:
            value, refs, snapshot = self.read()
        self.assertEqual(value, fixture.claim)
        self.assertEqual((refs[0].path, refs[0].sha256), (fixture.owner.claim_path, fixture.owner.claim_sha256))
        self.assertEqual(len(refs), 4)
        self.assertEqual(snapshot, str(fixture.snapshot))
        self.assertFalse(fixture.directory.exists())
        fixture.guard.assert_not_called()
        for callback in (live, write, mkdir, timer):
            callback.assert_not_called()

    def test_existing_live_holder_still_requires_real_empty_directory(self) -> None:
        """A data-only pass cannot bypass the live directory requirement."""
        fixture = self.fixture
        self.read()
        with self.assertRaises(FileNotFoundError):
            fixture.hold()
        fixture.directory.mkdir(mode=0o700)
        (fixture.directory / "TEST-prior-record").write_bytes(b"retained TEST bytes")
        with self.assertRaisesRegex(RuntimeError, "empty private owned"):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_live_holder_rechecks_source_after_metadata_only_pass(self) -> None:
        """No source-stat qualification is minted by reading small parent metadata."""
        fixture = self.fixture
        self.read()
        fixture.directory.mkdir(mode=0o700)
        os.link(fixture.source, fixture.root / "TEST-source-alias")
        with self.assertRaisesRegex(RuntimeError, "original owned regular"):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_changed_data_projection_cannot_mint_live_authority(self) -> None:
        """The live holder re-reads original refs instead of accepting this tuple."""
        fixture = self.fixture
        value, _refs, _snapshot = self.read()
        value["containerName"] = "TEST-not-an-owned-name"
        fixture.directory.mkdir(mode=0o700)
        held = fixture.hold()
        self.assertEqual(held.name, fixture.claim["containerName"])
        self.assertIs(held.owner, fixture.owner)

    def test_request_mutation_during_parent_reads_rejects(self) -> None:
        """Snapshot request types and bytes before any original runtime read."""
        fixture = self.fixture
        original = fixture._verify_runtime

        def mutate(runtime: dict, snapshot: str) -> None:
            """Change only the original in-memory TEST request after a real check."""
            original(runtime, snapshot)
            fixture.request["timeoutSeconds"] = 119

        with patch.object(intent, "verify_runtime_controls", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "metadata arguments changed"):
                self.read()
        fixture.guard.assert_not_called()
        self.assertFalse(fixture.directory.exists())

    def test_owner_mutation_during_parent_reads_cannot_be_rebaselined(self) -> None:
        """A read-time change cannot replace the original owner cutoff or guard."""
        fixture = self.fixture
        original = fixture._verify_runtime

        def mutate(runtime: dict, snapshot: str) -> None:
            """Change only the captured TEST deadline after checking actual files."""
            original(runtime, snapshot)
            object.__setattr__(fixture.owner, "deadline", fixture.owner.deadline + 1)

        with patch.object(intent, "verify_runtime_controls", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "metadata arguments changed"):
                self.read()
        fixture.guard.assert_not_called()

    def test_original_raw_parent_change_during_read_rejects(self) -> None:
        """Recheck all earlier raw holds after the last runtime inspection."""
        fixture = self.fixture
        original = fixture._verify_runtime

        def mutate(runtime: dict, snapshot: str) -> None:
            """Fault only the fixture's exact guarded input path, never dependencies."""
            original(runtime, snapshot)
            fixture.change(fixture.input_path, b"TEST changed original parent")

        with patch.object(intent, "verify_runtime_controls", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "metadata identity changed"):
                self.read()

    def test_same_closed_source_request_policy_checks_precede_live_handle(self) -> None:
        """Metadata-only preflight cannot soften the existing requested frame class."""
        self.fixture.request["frameCount"] = 25
        with self.assertRaisesRegex(ValueError, "differs from preclaim"):
            self.read()
        self.fixture.guard.assert_not_called()
        self.assertFalse(self.fixture.directory.exists())

    def assert_live_identity_fault(self, mutate: Callable[[], None]) -> None:
        """Inject only a TEST metadata mutation after a real execution-dir read."""
        fixture, fired = self.fixture, []
        if not fixture.directory.exists():
            fixture.directory.mkdir(mode=0o700)
        original = intent.directory_identity

        def observe(path: Path) -> tuple:
            """Retain real namespace checks, changing only the supplied TEST object."""
            value = original(path)
            if path == fixture.directory and not fired:
                fired.append(True)
                mutate()
            return value

        with patch.object(intent, "directory_identity", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "before live capture"):
                fixture.hold()
        self.assertEqual(fired, [True])
        fixture.guard.assert_not_called()

    def test_original_live_directory_read_cannot_rebaseline_request(self) -> None:
        """Reproduce the original claim24/request25 gap after the metadata pass."""
        self.assert_live_identity_fault(lambda: self.fixture.request.update(frameCount=25))

    def test_live_directory_read_cannot_rebaseline_owner_fields(self) -> None:
        """Protect original deadline types, guard and external raw claim identity."""
        owner = self.fixture.owner
        variants = (("deadline", owner.deadline + 1), ("guard", lambda: None), ("claim_sha256", "e" * 64))
        for key, changed in variants:
            previous = getattr(owner, key)
            self.assert_live_identity_fault(lambda: object.__setattr__(owner, key, changed))
            object.__setattr__(owner, key, previous)

    def test_original_final_parent_read_cannot_rebaseline_metadata(self) -> None:
        """Reproduce the final metadata helper mutation after the first comparison."""
        fixture, calls = self.fixture, []
        original = intent.directory_identity

        def observe(path: Path) -> tuple:
            """Mutate only after the exact second real prospective-parent read."""
            value = original(path)
            if path == fixture.directory.parent:
                calls.append(path)
            if len(calls) == 2:
                fixture.request["frameCount"] = 25
            return value

        with patch.object(intent, "directory_identity", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "metadata arguments changed during read"):
                self.read()
        self.assertEqual(len(calls), 2)
        self.assertFalse(fixture.directory.exists())
        fixture.guard.assert_not_called()

    def test_live_source_stat_cannot_rebaseline_request(self) -> None:
        """Carry the entry request through the source's actual last identity read."""
        fixture, fired = self.fixture, []
        fixture.directory.mkdir(mode=0o700)
        original = os.lstat

        def observe(path: object, *args: object, **kwargs: object) -> os.stat_result:
            """Retain actual stats and mutate only after the source target is read."""
            value = original(path, *args, **kwargs)
            if str(path) == str(fixture.source) and not fired:
                fired.append(True)
                fixture.request["timeoutSeconds"] = 119
            return value

        with patch.object(intent.os, "lstat", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "before live capture"):
                fixture.hold()
        self.assertEqual(fired, [True])
        fixture.guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
