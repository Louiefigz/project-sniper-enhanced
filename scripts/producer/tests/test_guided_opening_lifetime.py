"""Actual opening lifetime boundaries over tiny TEST files; no media execution."""
from __future__ import annotations

from copy import deepcopy
import time
import unittest
from unittest.mock import patch

import guided_opening_lifetime as lifetime
from _guided_opening_lifetime_fixture import OpeningLifetimeFixture
from guided_opening_execution import opening_clock


class OpeningLifetimeTest(unittest.TestCase):
    """Keep original identities while proving repeated guards do no byte reads."""

    def test_repeated_guards_do_not_hash_sources_or_tools(self) -> None:
        """Initial source capture is reused;100 actual guards have no file-hash calls."""
        f = OpeningLifetimeFixture(self)
        with patch("guided_body_execution.file_hash", wraps=lifetime.hold_body_file.__globals__["file_hash"]) as hashes:
            held = f.hold()
            self.assertNotIn(str(f.paths["media/TEST-source.bin"]), [str(call.args[0]) for call in hashes.call_args_list])
            initial = hashes.call_count
            started = time.monotonic()
            for _ in range(100):
                held.guard()
            self.assertEqual(hashes.call_count, initial)
            print(f"TEST opening lifetime100 guards: {(time.monotonic() - started) * 1000:.3f}ms; no new byte hashes")
        self.assertIs(held.clock, f.clock)
        self.assertIs(held.capture, f.inputs.verified_media)

    def test_each_original_dependency_change_rejects(self) -> None:
        """Code, template, tool, original source and control drift remain distinct."""
        for name in ("input.json", "claim.json", "docs/TEST-plan.json", "repo/scripts/TEST.py",
                     "pipeline/files/scripts/TEST.py", "pipeline/files/templates/TEST.html",
                     "pipeline/pipeline-lock.json", "pipeline/files/TEST-approval.json",
                     "tools/python", "tools/ffmpeg", "tools/ffprobe", "tools/docker", "media/TEST-source.bin"):
            with self.subTest(name=name):
                f = OpeningLifetimeFixture(self)
                held = f.hold()
                f.change(name)
                self.assertRaises(RuntimeError, held.guard)

    def test_initial_source_mutation_is_not_rebaselined(self) -> None:
        """A new holder cannot adopt a snapshot changed after initial admission."""
        f = OpeningLifetimeFixture(self)
        f.change("media/TEST-source.bin")
        with self.assertRaisesRegex(RuntimeError, "snapshot identity changed"):
            f.hold()

    def test_original_metadata_and_clock_are_not_replaceable(self) -> None:
        """Equal-looking copies, method override and scalar mutation cannot renew work."""
        mutations = (
            lambda f, h: f.inputs.documents["candidatePlan"].update(TEST="changed"),
            lambda f, h: f.claim.value.update(TEST="changed"),
            lambda f, h: f.pipeline.update(pinnedFileCount=2.0),
            lambda f, h: setattr(h, "clock", opening_clock(60)),
            lambda f, h: setattr(f.clock, "remaining", lambda: 60),
            lambda f, h: setattr(h, "pipeline", deepcopy(f.pipeline)),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                f = OpeningLifetimeFixture(self)
                held = f.hold()
                mutate(f, held)
                self.assertRaises(RuntimeError, held.guard)

    def test_original_directory_identity_survives_inode_preserving_move(self) -> None:
        """Moving a file into a replacement directory cannot keep its old ancestry."""
        f = OpeningLifetimeFixture(self)
        held = f.hold()
        parent = f.root / "media"
        moved = f.root / "TEST-old-media"
        parent.rename(moved)
        parent.mkdir()
        (moved / "TEST-source.bin").rename(parent / "TEST-source.bin")
        with self.assertRaisesRegex(RuntimeError, "ancestry changed"):
            held.guard()

    def test_clock_appends_are_allowed_but_original_history_is_not_rewritten(self) -> None:
        """Normal phase telemetry appends; original entry events remain immutable."""
        f = OpeningLifetimeFixture(self)
        f.clock.events.append({"stage": "TEST-entry", "elapsedMs": 1})
        held = f.hold()
        f.clock.events.append({"stage": "TEST-next", "elapsedMs": 2})
        held.guard()
        f.clock.events[0]["elapsedMs"] = 2
        with self.assertRaises(RuntimeError):
            held.guard()

    def test_final_original_clock_expiry_rejects(self) -> None:
        """Neither constructor time nor a later guard gets a replacement allowance."""
        f = OpeningLifetimeFixture(self)
        held = f.hold()
        with patch("guided_opening_execution.time.monotonic", return_value=f.clock.end):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                held.guard()

    def test_last_source_check_cannot_mutate_metadata_into_success(self) -> None:
        """The final source observer is closed against entry metadata and original time."""
        f = OpeningLifetimeFixture(self)
        held = f.hold()
        original = lifetime.assert_verified_snapshots
        def changed(*args: object) -> None:
            """Invalidate only in-memory TEST plan data after the actual source check."""
            original(*args)
            f.inputs.documents["candidatePlan"]["TEST"] = "changed"
        with patch.object(lifetime, "assert_verified_snapshots", side_effect=changed):
            with self.assertRaises(RuntimeError):
                held.guard()


if __name__ == "__main__":
    unittest.main()
