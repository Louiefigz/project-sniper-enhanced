"""Actual picture-command hooks with native/file/publication leaves stubbed."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch
import unittest

from audio import master as picture
from audio import render_audio_cache as cache
from audio import render_audio_master as audio
import render


class SourceColorPictureTransportTests(unittest.TestCase):
    """Test code-only guard transport without treating mocks as source authority."""

    def spec(self) -> picture.MasterSpec:
        """Use nonexistent TEST paths; every actual process/file leaf is replaced."""
        return picture.MasterSpec("/TEST-unopened/source.mp4", "/TEST-unopened/output.mp4",
                                  fps=24, frame_count=24)

    def test_existing_and_guarded_encode_use_identical_original_command(self) -> None:
        """Optional checks do not alter encoding options or legacy call arguments."""
        spec, events = self.spec(), []
        terminal = subprocess.CompletedProcess([], 0, "", "")
        guard = lambda: events.append("guard")
        with patch.object(picture, "_run", return_value=terminal) as native, \
                patch.object(picture.os.path, "isfile", return_value=True):
            expected = picture.encode_picture_only(spec)
            command = native.call_args.args[0]
            observed = picture.encode_picture_only(spec, guard)
            self.assertEqual(native.call_args.args[0], command)
        self.assertEqual(expected, observed)
        self.assertEqual(events, ["guard", "guard", "guard", "guard"])

    def test_legacy_none_keeps_original_three_argument_encoder_dispatch(self) -> None:
        """Existing direct picture callers do not receive a new optional argument."""
        terminal = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(picture, "_encode", return_value=terminal) as encode, \
                patch.object(picture.os.path, "isfile", return_value=True):
            spec = self.spec()
            picture.encode_picture_only(spec)
        encode.assert_called_once_with(spec, False, None)

    def test_before_command_and_actual_pre_native_failures_prevent_native(self) -> None:
        """Both command construction and immediate encode admission retain the guard."""
        for failure in ((RuntimeError("TEST first"),), (None, RuntimeError("TEST pre-native"))):
            with patch.object(picture, "_run") as native:
                self.assertRaisesRegex(RuntimeError, "TEST", picture.encode_picture_only, self.spec(),
                                       Mock(side_effect=failure))
            native.assert_not_called()

    def test_native_return_followed_by_guard_failure_does_not_report_success(self) -> None:
        """A produced file is not an accepted output after source ownership fails."""
        guard = Mock(side_effect=(None, None, RuntimeError("TEST post-native")))
        with patch.object(picture, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")) as native:
            self.assertRaisesRegex(RuntimeError, "post-native", picture.encode_picture_only, self.spec(), guard)
        native.assert_called_once()

    def leaves(self, stack: ExitStack) -> tuple:
        """Stop at original publication while keeping real master dispatch logic."""
        bus = SimpleNamespace(frames=24, frame_rate="24/1", directory="/TEST-unopened/bus")
        stack.enter_context(patch.object(audio, "verify_source_bus"))
        stack.enter_context(patch.object(audio, "observe_picture_source", return_value=object()))
        stack.enter_context(patch.object(audio, "render_qualified_mix", return_value={"ok": True}))
        encode = stack.enter_context(patch.object(audio, "encode_picture_only", return_value={"ok": True}))
        publish = stack.enter_context(patch.object(audio, "seal_audio_record",
                                                  side_effect=RuntimeError("TEST publication")))
        return bus, encode, publish

    def test_same_guard_reaches_picture_encoder_and_prepublication(self) -> None:
        """The actual master passes the exact supplied function without JSON transport."""
        guard = Mock(side_effect=(None, RuntimeError("TEST final ownership")))
        with ExitStack() as stack:
            bus, encode, publish = self.leaves(stack)
            self.assertRaisesRegex(RuntimeError, "final ownership", audio.master_source_bus,
                                   self.spec(), bus, {}, guard)
        self.assertIs(encode.call_args.args[1], guard)
        publish.assert_not_called()

    def test_last_file_observation_cannot_return_after_original_guard_failure(self) -> None:
        """Final output existence bookkeeping does not move the success boundary."""
        guard = Mock(side_effect=(None, None, None, RuntimeError("TEST final file check")))
        with patch.object(picture, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                patch.object(picture.os.path, "isfile", return_value=True):
            self.assertRaisesRegex(RuntimeError, "final file check", picture.encode_picture_only, self.spec(), guard)

    def test_legacy_master_still_uses_one_argument_picture_call(self) -> None:
        """No source guard or callback is implicitly attached to old masters."""
        with ExitStack() as stack:
            bus, encode, _publish = self.leaves(stack)
            stack.enter_context(patch.object(audio, "file_sha256", side_effect=RuntimeError("TEST existing receipt")))
            bus.admission = SimpleNamespace(policy="source-float-v2", plan_hash="TEST")
            bus.receipt = {"receiptHash": "TEST"}
            self.assertRaisesRegex(RuntimeError, "existing receipt", audio.master_source_bus, self.spec(), bus, {})
        self.assertEqual(len(encode.call_args.args), 1)

    def test_late_output_hash_failure_prevents_master_receipt_publication(self) -> None:
        """The complete payload must precede the final prepublication ownership check."""
        invalidated = [False]

        def guard() -> None:
            """Model only the retained owner's refusal; never mutate a real source file."""
            if invalidated[0]:
                raise RuntimeError("TEST ownership changed during output hash")

        def hashed(_path: str) -> str:
            """Invalidate an in-memory TEST owner during the last payload observation."""
            invalidated[0] = True
            return "a" * 64

        with ExitStack() as stack:
            bus, _encode, publish = self.leaves(stack)
            bus.admission = SimpleNamespace(policy="source-float-v2", plan_hash="TEST")
            bus.receipt = {"receiptHash": "TEST"}
            publish.side_effect, publish.return_value = None, {"receiptHash": "b" * 64}
            stack.enter_context(patch.object(audio, "render_qualified_mix", return_value={"ok": True,
                "picture": {}, "audioClock": {}, "filter": "TEST", "delivery": {}, "mastering_note": None}))
            stack.enter_context(patch.object(audio, "file_sha256", side_effect=hashed))
            stack.enter_context(patch.object(audio, "finalize_master", return_value={"status": "done"}))
            self.assertRaisesRegex(RuntimeError, "ownership changed during output hash",
                                   audio.master_source_bus, self.spec(), bus, {}, guard)
        publish.assert_not_called()


class SourceColorBaseCacheGuardTests(unittest.TestCase):
    """Actual cache publishers with every path/read/write leaf memory-only."""

    def setUp(self) -> None:
        """Keep invalidation entirely in a TEST boolean, never a held file path."""
        self.invalidated = False

    def guard(self) -> None:
        """Model the same original owner's refusal after a publication callback."""
        if self.invalidated:
            raise RuntimeError("TEST base owner changed")

    def invalidate(self, *_args: object, **_kwargs: object) -> str:
        """Mutate only this test instance and return a synthetic digest."""
        self.invalidated = True
        return "a" * 64

    def leaves(self, stack: ExitStack) -> tuple:
        """Exercise real pointer construction without source or cache filesystem IO."""
        root = Path("/TEST-unopened/output")
        bus = SimpleNamespace(admission=SimpleNamespace(policy="source-float-v2"),
            directory=str(root / "bus"), path=str(root / "bus/dialogue.wav"), sha256="a" * 64,
            receipt={"receiptHash": "b" * 64})
        ctx = SimpleNamespace(plan={}, manifest={}, source_audio_bus=bus, out_dir=str(root),
                              audio_clock_policy="source-float-v2")
        stack.enter_context(patch("guided_presenter_base.require_presenter_base"))
        stack.enter_context(patch("guided_source_color_base_context.hold_source_color_base_guard",
                                  side_effect=lambda _ctx: (self.guard(), self.guard)[1]))
        stack.enter_context(patch.object(render, "fingerprint_record", return_value={"fingerprint": "TEST"}))
        stack.enter_context(patch("base_reuse.completed_base_binding", return_value={"TEST": "memory-only"}))
        stack.enter_context(patch.object(Path, "resolve", return_value=root))
        stack.enter_context(patch.object(cache, "_inside", return_value=root / "bus/bus-receipt.json"))
        stack.enter_context(patch.object(cache, "bound_json", return_value=bus.receipt))
        hashed = stack.enter_context(patch.object(cache, "file_hash", return_value="a" * 64))
        atomic = stack.enter_context(patch.object(cache, "write_json_atomic"))
        opened = stack.enter_context(patch("builtins.open", mock_open()))
        dumped = stack.enter_context(patch.object(render.json, "dump"))
        stack.enter_context(patch.object(render, "emit"))
        return ctx, hashed, atomic, opened, dumped

    def test_late_base_hash_prevents_pointer_and_both_cache_publications(self) -> None:
        """Reproduce the real late-hash boundary without opening even a TEST file."""
        with ExitStack() as stack:
            ctx, hashed, atomic, opened, _dumped = self.leaves(stack)
            hashed.side_effect = lambda path: self.invalidate() if path.name == "final.mp4" else "a" * 64
            self.assertRaisesRegex(RuntimeError, "base owner changed", render._write_base_artifacts,
                                   ctx, SimpleNamespace(output_duration=1), {})
        atomic.assert_not_called()
        opened.assert_not_called()

    def test_pointer_callback_failure_prevents_first_base_cache_write(self) -> None:
        """A pointer publication cannot make subsequent writes bypass the same owner."""
        with ExitStack() as stack:
            ctx, _hashed, atomic, opened, _dumped = self.leaves(stack)
            atomic.side_effect = self.invalidate
            self.assertRaisesRegex(RuntimeError, "base owner changed", render._write_base_artifacts,
                                   ctx, SimpleNamespace(output_duration=1), {})
        atomic.assert_called_once()
        opened.assert_not_called()

    def test_first_cache_callback_failure_prevents_second_base_cache_write(self) -> None:
        """After the first cache's callback, the second cache remains unpublished."""
        with ExitStack() as stack:
            ctx, _hashed, atomic, opened, dumped = self.leaves(stack)
            dumped.side_effect = self.invalidate
            self.assertRaisesRegex(RuntimeError, "base owner changed", render._write_base_artifacts,
                                   ctx, SimpleNamespace(output_duration=1), {})
        atomic.assert_called_once()
        opened.assert_called_once_with("/TEST-unopened/output/base.fingerprint.json", "w")

    def test_absent_source_context_keeps_original_pointer_call_shape(self) -> None:
        """Legacy base writing still invokes the pointer with exactly three arguments."""
        with ExitStack() as stack:
            ctx, _hashed, _atomic, opened, _dumped = self.leaves(stack)
            stack.enter_context(patch("guided_source_color_base_context.hold_source_color_base_guard", return_value=None))
            pointer = stack.enter_context(patch.object(cache, "write_source_bus_pointer", return_value=ctx.source_audio_bus.receipt))
            render._write_base_artifacts(ctx, SimpleNamespace(output_duration=1), {})
        pointer.assert_called_once_with("/TEST-unopened/output/final.mp4", ctx.out_dir, ctx.source_audio_bus)
        self.assertEqual(opened.call_count, 2)


if __name__ == "__main__":
    unittest.main()
