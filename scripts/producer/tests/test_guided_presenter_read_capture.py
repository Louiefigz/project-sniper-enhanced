"""Real tiny file/hash/pin lifetime tests without a media decoder or owned renderer."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_presenter_read_fixture import PresenterReadFixture
from guided_presenter_capture import acquire_presenter_read_context
from guided_presenter_probe_identity import presenter_stat_identity
from guided_presenter_read import verify_opening_presenter_layers


class PresenterReadCaptureTests(unittest.TestCase):
    """Cold evidence borrows original sources/time and never reacquires decoded assets."""

    def setUp(self) -> None:
        """Make genuine tiny held files with inherited explicit TEST decoder stubs."""
        self.fixture = PresenterReadFixture()
        self.addCleanup(self.fixture.close)

    def acquire(self) -> object:
        """Use the production context manager under the original fixture deadline."""
        item = self.fixture
        return acquire_presenter_read_context(item.inputs, item.base, item.capture.context)

    def test_real_tool_base_pins_verify_saved_graph_without_decode_and_expire_on_exit(self) -> None:
        """Neither observations nor owners are reconstructed from receipt JSON."""
        with patch("guided_presenter_observation.run_text", side_effect=AssertionError("no decode")):
            with self.acquire() as context:
                evidence = verify_opening_presenter_layers(self.fixture.pictures, context, ((), None))
                self.assertIs(evidence.executable, False)
                context.guard()
        with self.assertRaisesRegex(RuntimeError, "lifetime is closed"):
            context.guard()

    def test_wrong_base_sha_and_changed_source_block_before_yield(self) -> None:
        """An initial reference and a later stat cannot substitute for linked bytes."""
        item = self.fixture
        wrong = replace(item.base, sha256="0" * 64)
        with self.assertRaisesRegex(RuntimeError, "bytes or file identity"):
            with acquire_presenter_read_context(item.inputs, wrong, item.capture.context):
                self.fail("wrong base yielded")
        item.probe.path.write_bytes(b"TEST changed source")
        with self.assertRaises(RuntimeError):
            with self.acquire():
                self.fail("changed original source yielded")

    def test_changed_base_at_return_and_original_deadline_expiry_fail(self) -> None:
        """Even post-read mutation prevents a successful context-manager return."""
        with self.assertRaisesRegex(RuntimeError, "held base changed"):
            with self.acquire() as context:
                context.guard()
                Path(self.fixture.base.path).write_bytes(b"TEST late base mutation")

    def test_expired_original_deadline_prevents_new_tool_hash(self) -> None:
        """A cold read cannot renew the prior generation's expired allowance."""
        self.fixture.probe.deadline.expired = True
        with patch("guided_presenter_capture.pin_executable") as pin, \
                self.assertRaisesRegex(RuntimeError, "deadline expired"), self.acquire():
            self.fail("expired read yielded")
        pin.assert_not_called()

    def test_same_inode_parent_symlink_is_rejected_on_normal_context_exit(self) -> None:
        """Regression: lstat of the source leaf alone follows substituted parent links."""
        source = self.fixture.probe.path
        store = source.parent
        moved = store.with_name(store.name + "-TEST-moved")
        initial = presenter_stat_identity(source.lstat())
        try:
            with self.assertRaises(RuntimeError), self.acquire():
                store.rename(moved)
                store.symlink_to(moved, target_is_directory=True)
                self.assertEqual(initial, presenter_stat_identity(source.lstat()))
        finally:
            if store.is_symlink():
                store.unlink()
            if moved.exists():
                moved.rename(store)


class PresenterWorkerFenceTests(unittest.TestCase):
    """Current metadata support does not enable unfinished color/owner dispatch."""

    def test_opening_refuses_before_frames_templates_prepare_or_media(self) -> None:
        """Property presence, even null/empty, cannot be silently rendered away."""
        from guided_opening_media import _execute

        for value in (None, [], [{"TEST": "layout"}]):
            inputs = SimpleNamespace(documents={"candidatePlan": {"presenterLayouts": value}})
            with patch("guided_opening_media.executable_frames") as frames, \
                    self.assertRaisesRegex(RuntimeError, "unowned render"):
                _execute(inputs, Path("/TEST/no-work"), None, None)
            frames.assert_not_called()

    def test_body_refuses_before_templates_reuse_or_assembly(self) -> None:
        """An approved opening record cannot supply a missing live body/color owner."""
        from guided_body_media import _execute

        work = SimpleNamespace(inputs=SimpleNamespace(documents={"candidatePlan": {"presenterLayouts": []}}))
        with patch("guided_body_media.admit_body_templates") as templates:
            with self.assertRaisesRegex(RuntimeError, "unowned render"):
                _execute(work)
        templates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
