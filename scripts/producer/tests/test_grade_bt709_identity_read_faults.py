"""Final-callback/byte faults against exact named TEST-root artifacts only."""
from __future__ import annotations

import os
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from _grade_bt709_identity_fixture import Bt709IdentityFixture
from color import grade_bt709_identity_read as reader


class Bt709IdentityReadFaultTests(unittest.TestCase):
    """No callback may substitute held evidence, metadata or the original cutoff."""

    def setUp(self) -> None:
        """Create and seal real TEST metadata before arming any explicitly owned fault."""
        self.now = [1000.0]
        timer = patch.object(time, "monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.fixture = Bt709IdentityFixture()
        self.addCleanup(self.fixture.cleanup)
        self.fixture.context = replace(self.fixture.context, deadline=1300.0)
        self.completed = self.fixture.completed()

    def test_initial_hold_rejects_first_callback_same_byte_probe_rewrite(self) -> None:
        """The existing original nine-field identity is held before any read callback."""
        path = self.fixture.job / "execution/result/probe.json"
        self.fixture.guard.side_effect = lambda: self.fixture.rewrite(path)
        with self.assertRaisesRegex(RuntimeError, "evidence changed"):
            reader.read_bt709_identity_observation(self.completed)

    def test_actual_first_parser_return_cannot_change_in_later_guard(self) -> None:
        """Retain the actual parents object immediately, not a post-callback replacement."""
        parsed, loads = [], reader.json.loads

        def parse(raw: bytes) -> dict:
            """Capture only actual buffers read by the new metadata consumer."""
            result = loads(raw)
            parsed.append(result)
            return result

        def mutate() -> None:
            """Mutate only a TEST parsed object, never any dependency or source bytes."""
            if parsed:
                parsed[0]["binding"]["frameCount"] += 1

        self.fixture.guard.side_effect = mutate
        with patch.object(reader.json, "loads", side_effect=parse), self.assertRaisesRegex(RuntimeError, "parsed metadata"):
            reader.read_bt709_identity_observation(self.completed)

    def test_final_callback_rejects_nested_original_observation_mutation(self) -> None:
        """A later caller guard cannot replace the actual completed geometry binding."""
        actual = reader.validate_bt709_identity_records

        def arm(context: tuple, lines: object, terminal: dict) -> object:
            """Arm only after the real full metadata stream finishes successfully."""
            result = actual(context, lines, terminal)
            self.fixture.guard.side_effect = lambda: object.__setattr__(self.completed.observation.records.stream, "width", 1918)
            return result

        with patch.object(reader, "validate_bt709_identity_records", side_effect=arm), \
                self.assertRaisesRegex(RuntimeError, "typed observation changed|original completed metadata"):
            reader.read_bt709_identity_observation(self.completed)

    def test_final_callback_original_overall_expiry_prevents_return(self) -> None:
        """Same-object expiry is not masked by a successful full raw metadata replay."""
        actual = reader.validate_bt709_identity_records

        def arm(context: tuple, lines: object, terminal: dict) -> object:
            """Expire the original fake clock only at the final caller guard."""
            result = actual(context, lines, terminal)
            self.fixture.guard.side_effect = lambda: self.now.__setitem__(0, 1300.0)
            return result

        with patch.object(reader, "validate_bt709_identity_records", side_effect=arm), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            reader.read_bt709_identity_observation(self.completed)

    def test_changed_deadline_or_guard_is_not_a_new_read_authority(self) -> None:
        """Capture the original typed lifetime before invoking any replacement callback."""
        self.fixture.guard.side_effect = lambda: object.__setattr__(self.completed.context, "deadline", 1600.0)
        with self.assertRaisesRegex(RuntimeError, "original context changed"):
            reader.read_bt709_identity_observation(self.completed)

    def test_future_metadata_exact_numeric_type_substitution_refuses(self) -> None:
        """Small frozen values remain tamper checked without freezing caller-owned data."""
        result = reader.read_bt709_identity_observation(self.completed)
        object.__setattr__(result.metadata, "decoded_frame_count", 180.0)
        with self.assertRaisesRegex(RuntimeError, "original held evidence"):
            result.assert_current()

    def test_future_approval_flag_or_equal_metadata_object_substitution_refuses(self) -> None:
        """Do not accept changed false scope flags or an equal-valued replacement object."""
        result = reader.read_bt709_identity_observation(self.completed)
        original = result.metadata
        object.__setattr__(result, "metadata", replace(original))
        with self.assertRaisesRegex(RuntimeError, "original held evidence"):
            result.assert_current()
        object.__setattr__(result, "metadata", original)
        object.__setattr__(result, "base_render_applicable", True)
        with self.assertRaisesRegex(RuntimeError, "original held evidence"):
            result.assert_current()

    def test_returned_raw_buffer_cannot_differ_from_held_hash(self) -> None:
        """Hash the actual read return, not a prior path read with similar parsed content."""
        actual = reader.read_bytes

        def changed(path: object, maximum: int) -> bytes:
            """Change only a returned TEST buffer; leave every file and dependency untouched."""
            return actual(path, maximum) + b" "

        with patch.object(reader, "read_bytes", side_effect=changed), \
                self.assertRaisesRegex(RuntimeError, "raw metadata differs"):
            reader.read_bt709_identity_observation(self.completed)

    def test_replay_normalized_hash_must_equal_actual_original_return(self) -> None:
        """A changed replay record cannot mint supplemental evidence for another result."""
        actual = reader.validate_bt709_identity_records

        def different(context: tuple, lines: object, terminal: dict) -> object:
            """Substitute only the TEST replay result after the actual validator runs."""
            result = actual(context, lines, terminal)
            return replace(result, records=replace(result.records, records_sha256="a" * 64))

        with patch.object(reader, "validate_bt709_identity_records", side_effect=different), \
                self.assertRaisesRegex(RuntimeError, "actual original normalized observation"):
            reader.read_bt709_identity_observation(self.completed)

    def test_final_bookkeeping_cannot_hide_original_expiry(self) -> None:
        """Require the same cutoff after the last small binding comparison too."""
        actual, calls = reader._unchanged, []

        def expire(value: object, original: tuple) -> None:
            """Expire only after the last real initial-read binding check completes."""
            actual(value, original)
            calls.append(True)
            if len(calls) == 3:
                self.now[0] = 1300.0

        with patch.object(reader, "_unchanged", side_effect=expire), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            reader.read_bt709_identity_observation(self.completed)

    def test_equal_numeric_replay_width_is_not_the_actual_typed_observation(self) -> None:
        """Regression: dataclass equality previously accepted width1920 as float1920.0."""
        actual = reader.validate_bt709_identity_records

        def different(context: tuple, lines: object, terminal: dict) -> object:
            """Substitute only a synthetic returned record, never file or source content."""
            result = actual(context, lines, terminal)
            stream = replace(result.records.stream, width=float(result.records.stream.width))
            return replace(result, records=replace(result.records, stream=stream))

        with patch.object(reader, "validate_bt709_identity_records", side_effect=different), \
                self.assertRaisesRegex(RuntimeError, "actual original normalized observation"):
            reader.read_bt709_identity_observation(self.completed)

    def test_future_original_file_rewrite_is_detected_without_replay(self) -> None:
        """Original raw-file stat holds remain live even after initial metadata validation."""
        result = reader.read_bt709_identity_observation(self.completed)
        path = self.fixture.job / "execution/result/frames.ffprobe"
        self.fixture.rewrite(path)
        with patch.object(reader, "read_bytes") as raw, self.assertRaisesRegex(RuntimeError, "evidence changed"):
            result.assert_current()
        raw.assert_not_called()

    def test_read_callback_cannot_override_completed_validation_method(self) -> None:
        """Reject an instance method substitution rather than dispatching it as authority."""
        object.__setattr__(self.completed, "assert_current", lambda: None)
        with patch.object(reader, "read_bytes") as raw, self.assertRaisesRegex(RuntimeError, "methods or fields"):
            reader.read_bt709_identity_observation(self.completed)
        raw.assert_not_called()

    def test_fault_helper_refuses_dependency_target_before_any_write(self) -> None:
        """Only predeclared regular single-link files in this exact TEST root can mutate."""
        with self.assertRaisesRegex(RuntimeError, "TEST-root"):
            self.fixture.rewrite(reader.__file__)

    def test_fault_helper_refuses_aliases_before_any_rewrite(self) -> None:
        """Local symlink and hard-link aliases cannot widen the mutation allowlist."""
        original = self.fixture.job / "execution/result/probe.json"
        alias = self.fixture.root / "TEST-probe-alias"
        alias.symlink_to(original)
        self.fixture.allowed_faults.add(alias)
        with self.assertRaisesRegex(RuntimeError, "TEST-root"):
            self.fixture.rewrite(alias)
        hard = self.fixture.root / "TEST-probe-hardlink"
        os.link(original, hard)
        self.fixture.allowed_faults.add(hard)
        with self.assertRaisesRegex(RuntimeError, "single-link"):
            self.fixture.rewrite(hard)


if __name__ == "__main__":
    unittest.main()
