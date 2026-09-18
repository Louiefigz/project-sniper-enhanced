"""Actual TEMP raw metadata only. The existing current-body runtime leaf is TEST-stubbed."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _body_source_color_control_fixture import body_source_color_control_fixture
from cut_preview_io import digest
from guided_body_budget import bind_body_budget
from guided_body_execution import assert_body_files, body_clock
from guided_body_inputs import BodyControl, read_body_control, _document, _held, _source_color_files
from guided_body_source_color_replay import body_source_color_control_refs, join_body_source_color_controls


class BodySourceColorControlTests(unittest.TestCase):
    """Raw joins never assert native replay, live resources, or a real human approval."""

    def setUp(self) -> None:
        """Create named private fixture controls before any actual reader holds them."""
        self.temporary = tempfile.TemporaryDirectory(prefix="TEST-body-color-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        origin = int(datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp() * 1000)
        self.invocation, self.output = body_source_color_control_fixture(self.root, origin)
        self.runtime = patch("guided_body_inputs.verify_runtime_controls").start()
        self.addCleanup(patch.stopall)

    def read(self) -> BodyControl:
        """Use actual closed readers and hashes with only current runtime admission stubbed."""
        return read_body_control(self.invocation, self.output)

    def owned_file(self, file: Path) -> None:
        """Every fault requires an explicit canonical TEST-root single-link regular file."""
        self.assertTrue(file.is_relative_to(self.root))
        self.assertEqual(file.resolve(strict=True), file)
        info = file.lstat()
        self.assertTrue(file.is_file())
        self.assertEqual(info.st_nlink, 1)
        self.assertEqual(info.st_uid, os.getuid())

    def fault_file(self, file: Path) -> None:
        """Change only the explicitly validated original TEST control file."""
        self.owned_file(file)
        file.write_bytes(file.read_bytes() + b" ")

    def same_byte_file(self, file: Path) -> None:
        """Replace only one exact canonical TEST file with equal bytes and a fresh inode."""
        self.owned_file(file)
        temporary = file.with_name("TEST-replacement-" + file.name)
        with temporary.open("xb") as stream:
            stream.write(file.read_bytes())
        self.owned_file(temporary)
        temporary.replace(file)

    def test_raw_three_metadata_files_are_held_without_restoring_old_runtime(self) -> None:
        """Raw claim digest differs deliberately from semantic claimHash in this TEST fixture."""
        control = self.read()
        names = {"openingSourceColorInput", "openingSourceColorArchive", "openingExecutionClaim"}
        self.assertTrue(names.issubset(control.documents))
        replay = control.value["sourceColorReplay"]
        original = control.documents["heldInput"]["opening"]
        self.assertNotEqual(original["claimSha256"], replay["opening"]["claimHash"])
        self.assertEqual(digest(control.documents["openingExecutionClaim"]), replay["opening"]["claimHash"])
        self.assertEqual(len(control.value["references"]), 7)
        self.assertEqual(len(control.held_files), 12)
        self.runtime.assert_called_once_with(control.value["runtime"], control.documents["openingInput"]["pipeline"]["snapshotRoot"])
        assert_body_files(control.held_files, body_clock(10))

    def test_source_replay_uses_only_remaining_original_metadata_allocation(self) -> None:
        """One byte short across all three additional files refuses without a new allowance."""
        control = self.read()
        original = control.documents["heldInput"]["opening"]
        replay = control.value["sourceColorReplay"]
        total = sum(replay[key]["sizeBytes"] for key in ("input", "reservationArchive")) + Path(original["claimPath"]).stat().st_size
        files, remaining = _source_color_files(control.value, {}, original, total)
        self.assertEqual(len(files), 3)
        self.assertEqual(remaining, 0)
        with self.assertRaises(RuntimeError):
            _source_color_files(control.value, {}, original, total - 1)

    def test_raw_sidecar_archive_or_claim_change_refuses_before_runtime(self) -> None:
        """Explicit file mutations never touch source/tool inventories or a real active marker."""
        control = self.read()
        replay = control.value["sourceColorReplay"]
        paths = [Path(replay[key]["path"]) for key in ("input", "reservationArchive")]
        paths.append(Path(control.documents["heldInput"]["opening"]["claimPath"]))
        for file in paths:
            raw = file.read_bytes()
            self.runtime.reset_mock()
            self.fault_file(file)
            with self.assertRaises(RuntimeError):
                self.read()
            self.runtime.assert_not_called()
            file.write_bytes(raw)

    def test_held_versions_and_source_replay_cannot_be_downgraded_or_replaced(self) -> None:
        """Both exact wire copies are required; a source2 result cannot become legacy input."""
        control = self.read()
        claim = control.documents["admissionClaim"]
        for group, version in (("outer", 1), ("outer", True), ("inner", 1), ("inner", 2.0)):
            docs = deepcopy(control.documents)
            target = docs["heldInput"] if group == "outer" else docs["heldInput"]["input"]
            target["schemaVersion"] = version
            with self.assertRaises(RuntimeError):
                _held(control.value, docs, claim, self.root)

    def test_original_selection_cleanup_receipt_claim_and_source_hash_joins_are_exact(self) -> None:
        """Mutually plausible source metadata does not override independently held body bindings."""
        control = self.read()
        for key in ("selectionHash", "cleanupHash", "claimHash", "mediaResultSha256", "receiptHash", "sourceColorHash"):
            docs = deepcopy(control.documents)
            replay = docs["heldInput"]["input"]["sourceColorReplay"]
            (replay if key == "sourceColorHash" else replay["opening"])[key] = "0" * 64
            with self.assertRaises((RuntimeError, ValueError)):
                join_body_source_color_controls(replay, docs, docs["heldInput"]["opening"], self.root)

    def test_late_current_runtime_callback_cannot_replace_original_replay_metadata(self) -> None:
        """Original extra file identities are checked again after the existing runtime callback."""
        control = self.read()
        archive = Path(control.value["sourceColorReplay"]["reservationArchive"]["path"])
        self.runtime.side_effect = lambda *_args: self.fault_file(archive)
        with self.assertRaisesRegex(RuntimeError, "metadata changed"):
            self.read()

    def test_late_current_runtime_callback_cannot_change_returned_runtime_values(self) -> None:
        """Only source2 adds an original detached parsed-data hold around this existing callback."""
        def mutate(runtime: dict, _snapshot: str) -> None:
            """Change only the actual TEST runtime argument supplied by the reader."""
            runtime["imageId"] = "TEST changed current-body control"
        self.runtime.side_effect = mutate
        with self.assertRaises((RuntimeError, ValueError)):
            self.read()

    def test_input_activation_same_byte_replacement_cannot_be_rebaselined_after_runtime(self) -> None:
        """Both invocation files are held before the existing current-runtime callback."""
        def replace_input(*_args: object) -> None:
            """Substitute equal raw bytes at the exact fixture invocation path."""
            self.same_byte_file(self.invocation.input_path)
        self.runtime.side_effect = replace_input
        with self.assertRaisesRegex(RuntimeError, "metadata changed"):
            self.read()

    def test_original_invocation_field_identity_cannot_change_during_runtime_callback(self) -> None:
        """An equal copied Path is not the original direct invocation field."""
        def replace_path(*_args: object) -> None:
            """Substitute one equal original caller field in memory only."""
            object.__setattr__(self.invocation, "input_path", Path(str(self.invocation.input_path)))
        self.runtime.side_effect = replace_path
        with self.assertRaisesRegex(RuntimeError, "original invocation changed"):
            self.read()

    def test_parent_symlink_to_moved_original_archive_is_not_a_stable_control(self) -> None:
        """The leaf inode is preserved deliberately; original ancestry still must hold."""
        control = self.read()
        archive = Path(control.value["sourceColorReplay"]["reservationArchive"]["path"])
        def replace_parent(*_args: object) -> None:
            """Move only the exact previously validated TEST archive parent."""
            self.owned_file(archive)
            parent = archive.parent
            moved = parent.with_name("TEST-moved-original-attempt")
            parent.rename(moved)
            parent.symlink_to(moved, target_is_directory=True)
        self.runtime.side_effect = replace_parent
        with self.assertRaisesRegex(RuntimeError, "ancestry|metadata changed"):
            self.read()

    def test_original_body_budget_binds_once_without_new_source_allowance(self) -> None:
        """Only the existing budget owner binds wall time, not the metadata mirror."""
        control = self.read()
        clock = body_clock(10)
        end = clock.end
        now = int(datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp() * 1000) + 63_000
        with patch("guided_body_execution.time.time_ns", return_value=now * 1_000_000):
            bind_body_budget(control, clock)
            self.assertLessEqual(clock.end, end)
            self.assertGreater(clock.remaining(), 0)
            self.assertRaisesRegex(RuntimeError, "rebound", bind_body_budget, control, clock)

    def test_original_claim_paths_do_not_read_an_unrelated_owned_file(self) -> None:
        """Closed path roles reject before extra IO even for another valid TEST path."""
        control = self.read()
        original = deepcopy(control.documents["heldInput"]["opening"])
        original["claimPath"] = original["resultPath"]
        with patch("builtins.open", side_effect=AssertionError("TEST no file read")):
            self.assertRaisesRegex(ValueError, "path roles", body_source_color_control_refs, control.value["sourceColorReplay"], original)

    def test_archive_runtime_old_socket_and_source_declarations_are_only_metadata(self) -> None:
        """Original runtime/parent/plan/ref substitutions cannot become replay authority."""
        control = self.read()
        changes = [("openingSourceColorArchive", "runtime", "userId", "502:20"),
            ("openingSourceColorInput", "expected", "manifestSha256", "0" * 64),
            ("openingSourceColorInput", "reservation", "sha256", "0" * 64),
            ("openingSourceColorInput", "reservation", "sizeBytes", 1),
            ("openingSourceColorInput", "opening", "clockHash", "0" * 64),
            ("openingExecutionClaim", None, "requestId", "00000000-0000-4000-8000-000000000004")]
        for name, group, key, replacement in changes:
            docs = deepcopy(control.documents)
            (docs[name][group] if group else docs[name])[key] = replacement
            self.assertRaises((ValueError, RuntimeError), join_body_source_color_controls,
                control.value["sourceColorReplay"], docs, docs["heldInput"]["opening"], self.root)

    def reject_early_replacement(self, target: Path) -> None:
        """Use the actual parser; only the first returned TEST metadata callback faults."""
        called = False
        def returned(ref: object, maximum: int) -> tuple:
            """Substitute an exact TEST original after the first dependent JSON read."""
            nonlocal called
            result = _document(ref, maximum)
            if not called:
                called = True
                self.same_byte_file(target)
            return result
        self.runtime.reset_mock()
        with patch("guided_body_inputs._document", side_effect=returned):
            self.assertRaisesRegex(RuntimeError, "metadata changed", self.read)
        self.assertTrue(called)
        self.runtime.assert_not_called()

    def test_early_document_callback_cannot_rebaseline_original_input(self) -> None:
        """Original body input is captured before the first dependent JSON parser."""
        self.reject_early_replacement(self.invocation.input_path)

    def test_early_document_callback_cannot_rebaseline_original_activation(self) -> None:
        """Original activation is captured before the first dependent JSON parser."""
        self.reject_early_replacement(self.invocation.activation_path)

    def test_early_document_callback_cannot_rebaseline_original_opening_result(self) -> None:
        """All seven original refs are captured before even an earlier parser callback."""
        original = self.read().documents["heldInput"]["opening"]
        self.reject_early_replacement(Path(original["resultPath"]))

    def test_early_document_callback_cannot_rebaseline_original_sidecar(self) -> None:
        """The replay sidecar is stat-held before any ordinary dependent parser."""
        replay = self.read().value["sourceColorReplay"]
        self.reject_early_replacement(Path(replay["input"]["path"]))

    def test_early_document_callback_cannot_rebaseline_original_archive(self) -> None:
        """The final archive is stat-held before any ordinary dependent parser."""
        replay = self.read().value["sourceColorReplay"]
        self.reject_early_replacement(Path(replay["reservationArchive"]["path"]))

    def test_early_document_callback_cannot_rebaseline_original_claim(self) -> None:
        """Exact derived claim identity predates parsing its separately held raw SHA."""
        original = self.read().documents["heldInput"]["opening"]
        self.reject_early_replacement(Path(original["claimPath"]))
