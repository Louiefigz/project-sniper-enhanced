"""Worker transport/composition tests; every execution/admission leaf is explicitly TEST-stubbed."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import guided_opening_media as worker
from guided_opening_execution import opening_clock
import guided_source_color_media as media
from palmier.process_deadline import use_process_deadline


def values() -> tuple:
    """Use only uncreated absolute TEST names; parsing never opens them."""
    return ("/TEST-unopened/source-color/input.json", "a" * 64, "/TEST-unopened/producer", "/TEST-unopened/resource")


def argv() -> list[str]:
    """Required original worker transport remains unchanged."""
    return ["guided_opening_media.py", "/TEST-unopened/input.json", "/TEST-unopened/output",
            "--input-sha256", "b" * 64, "--timeout-seconds", "25", "--execution-claim",
            "/TEST-unopened/claim.json", "--execution-claim-sha256", "c" * 64]


class SourceColorMediaInvocationTests(unittest.TestCase):
    """No parser/dispatch success represents an actual source, renderer, media or quality result."""

    def test_all_or_none_exact_transport(self) -> None:
        """Do not infer sidecars, declarations or a fallback from partial flags."""
        self.assertIsNone(media.parse_source_color_media_invocation((None,) * 4))
        result = media.parse_source_color_media_invocation(values())
        self.assertEqual((str(result.input_path), result.input_sha256, str(result.producer_dir), str(result.resource_dir)), values())
        media.validate_source_color_media_invocation(result)
        for index in range(4):
            partial = list(values())
            partial[index] = None
            self.assertRaisesRegex(ValueError, "four.*together", media.parse_source_color_media_invocation, tuple(partial))

    def test_path_and_hash_normalization_are_not_silent(self) -> None:
        """Reject caller aliases before constructing Path or touching a directory."""
        for bad in ("relative", "/a/../b", "/a/./b", "/a//b", "//a", "/a/", "/a\\b", "/a\x00b", ""):
            changed = list(values())
            changed[0] = bad
            self.assertRaises(ValueError, media.parse_source_color_media_invocation, tuple(changed))
        for bad in ("A" * 64, "x", True, 1):
            self.assertRaises((ValueError, RuntimeError), media.parse_source_color_media_invocation,
                              (values()[0], bad, *values()[2:]))

    def test_direct_malformed_call_refuses_before_clock_directory_or_claim(self) -> None:
        """A JSON DTO cannot skip the direct-call optional transport check."""
        with patch.object(worker, "_directory") as directory, patch.object(worker, "opening_clock") as clock:
            self.assertRaises(ValueError, worker.run, Path("/TEST/input"), Path("/TEST/output"),
                              ("a" * 64, 30, Path("/TEST/claim"), "b" * 64), {"TEST": "not invocation"})
        directory.assert_not_called()
        clock.assert_not_called()

    def test_main_partial_flags_fail_without_run(self) -> None:
        """Actual CLI grammar cannot execute a legacy fallback for partial source color."""
        with patch("sys.argv", [*argv(), "--source-color-input", values()[0]]), patch.object(worker, "run") as run, \
                redirect_stderr(StringIO()), redirect_stdout(StringIO()):
            self.assertEqual(worker.main(), 1)
        run.assert_not_called()

    def test_main_legacy_dispatch_preserves_three_argument_call(self) -> None:
        """Absent source flags preserve the preexisting direct entry signature."""
        with patch("sys.argv", argv()), patch.object(worker, "run", return_value={"TEST": True}) as run, \
                redirect_stdout(StringIO()):
            self.assertEqual(worker.main(), 0)
        self.assertEqual(len(run.call_args.args), 3)

    def test_main_explicit_transport_passes_one_typed_fourth_argument(self) -> None:
        """No declarations or authority values are synthesized in the CLI."""
        flags = ("input", "input-sha256", "producer-dir", "resource-dir")
        extra = [value for flag, value in zip(flags, values()) for value in ("--source-color-" + flag, value)]
        with patch("sys.argv", [*argv(), *extra]), patch.object(worker, "run", return_value={"TEST": True}) as run, \
                redirect_stdout(StringIO()):
            self.assertEqual(worker.main(), 0)
        self.assertEqual(len(run.call_args.args), 4)
        self.assertIs(type(run.call_args.args[3]), media.SourceColorMediaInvocation)

    def test_unsupported_source_plan_refuses_before_lifetime_or_observation(self) -> None:
        """Reject unsupported work before spending the existing decode allowance."""
        invocation = media.parse_source_color_media_invocation(values())
        with patch.object(media, "assert_source_color_plan", side_effect=RuntimeError("TEST unsupported")), \
                patch.object(media, "OpeningSourceLifetime") as lifetime, patch.object(media, "observe_opening_source_colors") as observe:
            self.assertRaisesRegex(RuntimeError, "unsupported", media.prepare_source_color_media,
                                   object(), object(), (Path("/TEST"), opening_clock(20), {}), invocation)
        lifetime.assert_not_called()
        observe.assert_not_called()

    def test_actual_clock_and_same_guard_cross_the_adapter_with_no_nested_observation_alarm(self) -> None:
        """Only orchestration is under test; no mocked leaf grants any original-owner authority."""
        clock, guard = opening_clock(20), Mock()
        inputs, claim, pipeline, prepared = object(), object(), {}, object()
        lifetime, context = SimpleNamespace(guard=guard), object()
        invocation = media.parse_source_color_media_invocation(values())
        with ExitStack() as stack:
            stack.enter_context(patch.object(media, "assert_source_color_plan"))
            make_lifetime = stack.enter_context(patch.object(media, "OpeningSourceLifetime", return_value=lifetime))
            observe = stack.enter_context(patch.object(media, "observe_opening_source_colors", side_effect=lambda *_:
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0) or "TEST-batch"))
            hold = stack.enter_context(patch.object(media, "hold_bt709_base_identity", return_value="TEST-identity"))
            constructor = stack.enter_context(patch.object(media, "SourceColorBaseContext", return_value=context))
            constructor.assert_current = Mock()
            prepare = stack.enter_context(patch.object(media, "prepare_source_color_full_program", return_value=prepared))
            with use_process_deadline(clock):
                self.assertEqual(media.prepare_source_color_media(inputs, claim, (Path("/TEST"), clock, pipeline), invocation), (prepared, context))
        self.assertEqual(make_lifetime.call_args.args, (inputs, claim, pipeline, clock))
        original = observe.call_args.args[1]
        self.assertIs(original.clock, clock)
        original.authority.guard()
        guard.assert_called_once()
        self.assertEqual(constructor.call_args.args, (inputs, clock, "TEST-identity", original.authority.guard))
        self.assertIs(prepare.call_args.args[2], context)
        hold.assert_called_once_with("TEST-batch")
        self.assertEqual([row["stage"] for row in clock.events], ["source-color-original-lifetime",
            "source-color-bt709-identity", "ordinary-full-program-preparation"])

    def test_source_observation_failure_never_attempts_base_or_legacy_fallback(self) -> None:
        """Existing source errors propagate; partial all-source work is not usable media."""
        invocation = media.parse_source_color_media_invocation(values())
        with patch.object(media, "assert_source_color_plan"), \
                patch.object(media, "OpeningSourceLifetime", return_value=SimpleNamespace(guard=Mock())), \
                patch.object(media, "observe_opening_source_colors", side_effect=RuntimeError("TEST failed source")), \
                patch.object(media, "prepare_source_color_full_program") as prepare:
            self.assertRaisesRegex(RuntimeError, "failed source", media.prepare_source_color_media,
                object(), object(), (Path("/TEST"), opening_clock(20), {}), invocation)
        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
