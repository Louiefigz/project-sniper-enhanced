"""Exact grade preclaim metadata/publication tests; no worker/media authority."""
from __future__ import annotations

import json
import os
import stat
import time
import unittest
from unittest.mock import patch

from _grade_launch_fixture import GradeLaunchFixture
from cut_preview_io import file_hash
from headless import grade_launch_files as files
from headless.grade_launch_intent import OwnedGradeLaunch


class GradeLaunchIntentTests(unittest.TestCase):
    """Real tiny files; socket-type TEST stub, no Docker or decoder invocation."""

    def setUp(self) -> None:
        """Construct a fresh independently held TEST preclaim."""
        self.fixture = GradeLaunchFixture()
        self.addCleanup(self.fixture.close)

    def test_exact_raw_preclaim_and_new_readonly_records(self) -> None:
        """Bind original raw refs and publish only exact new read-only records."""
        fixture = self.fixture
        held = fixture.hold()
        self.assertEqual(held.name, fixture.claim["containerName"])
        self.assertEqual(held.deadline, fixture.owner.deadline)
        raw_sha = held.before_launch(fixture.runtime, fixture.command())
        held.after_launch("e" * 64)
        intent = fixture.directory / "launch-intent.json"
        response = fixture.directory / "launch-response.json"
        self.assertEqual(raw_sha, file_hash(intent))
        self.assertEqual(json.loads(response.read_text())["launchIntentSha256"], raw_sha)
        self.assertEqual(stat.S_IMODE(intent.stat().st_mode), 0o400)
        self.assertEqual(stat.S_IMODE(response.stat().st_mode), 0o400)
        self.assertNotEqual(fixture.runtime_controls["runtimeRepoRoot"], str(fixture.snapshot))
        held.check()

    def test_closed_claim_and_typed_source_expectations(self) -> None:
        """Reject unknown keys, wrong identities and equal-valued numeric drift."""
        fixture = self.fixture
        bad = [("schemaVersion", True), ("frameCount", 24.0), ("containerName", "unclaimed"),
               ("profile", "unknown"), ("sourceSha256", "b" * 64), ("unknown", None)]
        for key, value in bad:
            fixture.change(fixture.claim_path, {**fixture.claim, key: value})
            fixture.owner = fixture.owner_for_current_claim()
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                fixture.hold()
        fixture.guard.assert_not_called()

    def test_claim_raw_hash_is_not_a_resealed_json_digest(self) -> None:
        """A semantically equal rewrite cannot replace the owner's raw claim SHA."""
        fixture = self.fixture
        fixture.change(fixture.claim_path, fixture.claim)
        with self.assertRaisesRegex(RuntimeError, "hash changed"):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_expired_original_deadline_does_not_invoke_guard(self) -> None:
        """An expired claim cannot start callbacks or publication work."""
        fixture = self.fixture
        fixture.owner = OwnedGradeLaunch(fixture.claim_path, file_hash(fixture.claim_path), time.monotonic() - 1, fixture.guard)
        with self.assertRaises(RuntimeError):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_first_callback_cannot_replace_deadline(self) -> None:
        """Capture the actual original deadline before the first callback."""
        fixture = self.fixture
        fixture.guard.side_effect = lambda: object.__setattr__(fixture.owner, "deadline", time.monotonic() + 999)
        with self.assertRaisesRegex(RuntimeError, "original arguments"):
            fixture.hold()

    def test_first_callback_cannot_mutate_original_request(self) -> None:
        """Do not rebaseline the request after an ownership callback changes it."""
        fixture = self.fixture
        fixture.guard.side_effect = lambda: fixture.request.update(frameCount=25)
        with self.assertRaisesRegex(RuntimeError, "original arguments"):
            fixture.hold()

    def test_parent_metadata_late_change_is_rejected(self) -> None:
        """Original input bytes remain bound after every owner callback."""
        fixture = self.fixture
        held = fixture.hold()
        fixture.guard.side_effect = lambda: fixture.change(fixture.input_path, b"changed TEST input")
        with self.assertRaisesRegex(RuntimeError, "metadata identity"):
            held.check()

    def test_changed_source_stays_unadmitted(self) -> None:
        """A changed source identity cannot inherit earlier metadata validation."""
        fixture = self.fixture
        held = fixture.hold()
        fixture.change(fixture.source, b"changed TEST source")
        with self.assertRaisesRegex(RuntimeError, "source identity"):
            held.check()

    def test_actual_final_command_must_match_fixed_builder(self) -> None:
        """The caller cannot change the request embedded in the actual argv."""
        fixture = self.fixture
        held = fixture.hold()
        command = fixture.command()
        command[-1] = json.dumps({**fixture.request, "frameCount": 25})
        with self.assertRaisesRegex(RuntimeError, "command differs"):
            held.before_launch(fixture.runtime, command)
        self.assertFalse((fixture.directory / "launch-intent.json").exists())

    def test_command_callback_mutation_rejects_before_publication(self) -> None:
        """Callback edits to the original command must prevent launch intent."""
        fixture = self.fixture
        held = fixture.hold()
        command = fixture.command()
        fixture.guard.side_effect = lambda: command.append("TEST unauthorized extra arg")
        with self.assertRaisesRegex(RuntimeError, "runtime/command changed"):
            held.before_launch(fixture.runtime, command)
        self.assertFalse((fixture.directory / "launch-intent.json").exists())

    def test_publication_is_one_shot_and_collision_retains_original(self) -> None:
        """A collided publication cannot overwrite evidence or retry its owner."""
        fixture = self.fixture
        held = fixture.hold()
        target = fixture.directory / "launch-intent.json"
        target.write_bytes(b"TEST prior record")
        with self.assertRaises(RuntimeError):
            held.before_launch(fixture.runtime, fixture.command())
        self.assertEqual(target.read_bytes(), b"TEST prior record")
        with self.assertRaisesRegex(RuntimeError, "reused"):
            held.before_launch(fixture.runtime, fixture.command())

    def test_partial_write_is_retained_and_cannot_retry(self) -> None:
        """Persisting a partial intent never grants an automatic second attempt."""
        fixture = self.fixture
        held = fixture.hold()
        with patch.object(files, "write_all", side_effect=OSError("TEST ENOSPC")):
            with self.assertRaisesRegex(OSError, "ENOSPC"):
                held.before_launch(fixture.runtime, fixture.command())
        self.assertTrue((fixture.directory / "launch-intent.json").exists())
        with self.assertRaisesRegex(RuntimeError, "reused"):
            held.before_launch(fixture.runtime, fixture.command())

    def test_response_survives_original_guard_failure(self) -> None:
        """Retain an exact launch response even if the following owner check fails."""
        fixture = self.fixture
        held = fixture.hold()
        held.before_launch(fixture.runtime, fixture.command())
        fixture.guard.side_effect = RuntimeError("TEST lost original owner")
        with self.assertRaisesRegex(RuntimeError, "lost original owner"):
            held.after_launch("f" * 64)
        self.assertEqual(json.loads((fixture.directory / "launch-response.json").read_text())["containerId"], "f" * 64)
        with self.assertRaises(RuntimeError):
            held.after_launch("f" * 64)

    def test_postresponse_callback_cannot_change_runtime(self) -> None:
        """An actual returned ID does not excuse a changed original runtime."""
        fixture = self.fixture
        held = fixture.hold()
        held.before_launch(fixture.runtime, fixture.command())
        fixture.guard.side_effect = lambda: fixture.runtime.approval.update(testOnly=False)
        with self.assertRaisesRegex(RuntimeError, "runtime/command changed"):
            held.after_launch("f" * 64)

    def test_postresponse_callback_cannot_change_original_intent(self) -> None:
        """Keep prelaunch evidence immutable through the postresponse callback."""
        fixture = self.fixture
        held = fixture.hold()
        held.before_launch(fixture.runtime, fixture.command())
        target = fixture.directory / "launch-intent.json"
        fixture.guard.side_effect = lambda: fixture.change(target, b"TEST changed local intent")
        with self.assertRaisesRegex(RuntimeError, "metadata identity"):
            held.after_launch("f" * 64)

    def test_hardlinked_parent_metadata_rejects_before_callback(self) -> None:
        """Refuse aliased original metadata before any ownership callback."""
        fixture = self.fixture
        os.link(fixture.input_path, fixture.root / "input-alias.json")
        with self.assertRaisesRegex(RuntimeError, "single-link"):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_fault_writer_cannot_mutate_production_dependencies(self) -> None:
        """Fault helpers must reject actual dependency paths without writing."""
        from pathlib import Path

        production = Path(files.__file__).resolve()
        original = file_hash(production)
        with self.assertRaisesRegex(RuntimeError, "TEST root"):
            self.fixture.change(production, b"NEVER WRITE")
        self.assertEqual(file_hash(production), original)

    def test_v2_request_is_explicit_without_renewing_parent_deadline(self) -> None:
        """An explicit longer class never renews the original parent's cutoff."""
        fixture = self.fixture
        fixture.enable_v2()
        held = fixture.hold()
        held.before_launch(fixture.runtime, fixture.command())
        self.assertEqual(held.deadline, fixture.owner.deadline)
        self.assertLess(held.deadline - time.monotonic(), 121)
        self.assertEqual(fixture.request["timeoutSeconds"], 1200)

    def test_original_input_job_mismatch_rejects_before_callback(self) -> None:
        """The raw grade input must describe the exact claimed job directory."""
        fixture = self.fixture
        value = json.loads(fixture.input_path.read_text())
        value["jobId"] = "00000000-0000-4000-8000-000000000000"
        fixture.change(fixture.input_path, value)
        fixture.change(fixture.claim_path, {**fixture.claim, "inputSha256": file_hash(fixture.input_path)})
        fixture.owner = fixture.owner_for_current_claim()
        with self.assertRaisesRegex(ValueError, "original project job"):
            fixture.hold()
        fixture.guard.assert_not_called()

    def test_original_runtime_tool_bytes_rechecked_after_callback(self) -> None:
        """Recheck original tool bytes rather than accepting its current path."""
        from pathlib import Path

        fixture = self.fixture
        held = fixture.hold()
        fixture.guard.side_effect = lambda: fixture.change(Path(fixture.runtime.docker), b"TEST changed executable")
        with self.assertRaisesRegex(RuntimeError, "executable changed"):
            held.check()

    def test_response_id_and_original_record_metadata_are_closed(self) -> None:
        """Reject malformed IDs and substitutions inside frozen record objects."""
        fixture = self.fixture
        held = fixture.hold()
        held.before_launch(fixture.runtime, fixture.command())
        with self.assertRaisesRegex(RuntimeError, "exact new container ID"):
            held.after_launch("f" * 64 + "\n")
        self.assertFalse((fixture.directory / "launch-response.json").exists())
        fixture.guard.side_effect = lambda: object.__setattr__(held._publication, "raw", b"TEST substituted raw record")
        with self.assertRaisesRegex(RuntimeError, "publication binding changed"):
            held.check()

    def test_file_and_directory_fsync_both_precede_intent_success(self) -> None:
        """Durability includes the newly named file's containing directory."""
        fixture = self.fixture
        held = fixture.hold()
        synced = []
        original = os.fsync

        def observe(descriptor: int) -> None:
            """Record actual descriptor roles while retaining the real fsync."""
            synced.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
            original(descriptor)

        with patch.object(files.os, "fsync", side_effect=observe):
            held.before_launch(fixture.runtime, fixture.command())
        self.assertEqual(synced, [stat.S_IFREG, stat.S_IFDIR])


if __name__ == "__main__":
    unittest.main()
