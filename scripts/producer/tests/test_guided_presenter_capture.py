"""Real pin/capture control flow with explicit stubbed decoder output only."""
from __future__ import annotations

import os
import subprocess
import unittest
from dataclasses import replace
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture
import guided_presenter_capture as module
from guided_presenter_observation import observe_presenter_asset
from guided_presenter_probe_identity import presenter_stat_identity
from guided_presenter_profile import presenter_graph_workload
from guided_proposal_presenter import guided_presenter_policy
from headless.runtime_executable_pins import close_pins


class GuidedPresenterCaptureTests(unittest.TestCase):
    """No decoder, isolated admission, native render, rights or approval claims."""

    def setUp(self) -> None:
        """Create small real TEST files before the acquisition under test."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)
        self.inputs, self.context = self.fixture.inputs, self.fixture.context

    def results(self) -> list:
        """Return explicit current-shaped TEST stdout; never invoke a real process."""
        return [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.probe.raw()]

    def assert_closed(self, pin: object) -> None:
        """Every held tool descriptor, including ancestors, must be closed at exit."""
        for fd in (pin.fd, *(node.fd for node in pin.directories)):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_actual_v8_repeated_windows_observe_once_keep_clock_and_close_lifetime(self) -> None:
        """Only two stubbed calls for one asset, with exact original identities and pins."""
        with patch("guided_presenter_observation.run_text", side_effect=self.results()) as runner, \
                patch.object(module, "observe_presenter_asset", wraps=observe_presenter_asset) as observe, \
                patch.object(module, "close_pins", wraps=close_pins) as close, \
                patch("guided_presenter_capture_inputs.presenter_graph_workload", wraps=presenter_graph_workload) as workload, \
                patch("headless.external_media_snapshot._hash_descriptor") as source_hash:
            with module.acquire_presenter_execution(self.inputs, self.context) as owner:
                graph = owner.full_graph()
                self.assertEqual([row.operation_index for row in graph.windows], [0, 1])
                self.assertIs(owner.runtime.deadline, self.context.deadline)
                self.assertEqual(owner.observed[0].source.stat_identity, self.fixture.probe.source.stat_identity)
                self.assertEqual(owner.runtime.ffprobe.stat_identity,
                                 presenter_stat_identity(os.stat(self.context.tools["ffprobe"]["path"])))
                self.assertEqual(len(owner.held_assets()), 1)
            self.assertEqual(observe.call_count, 1)
            self.assertEqual(runner.call_count, 2)
            self.assertEqual(workload.call_count, 2)  # Declared preflight, then actual observed dimensions.
            self.assertTrue(all(call.args[3] == ((64, 36), (64, 36)) for call in workload.call_args_list))
            source_hash.assert_not_called()
            close.assert_called_once()
        self.assert_closed(close.call_args.args[0][0])
        with self.assertRaisesRegex(RuntimeError, "lifetime is closed"):
            owner.full_graph()

    def test_noop_validates_real_request_without_tool_or_source_capture(self) -> None:
        """No presenter does not require even a declared probe or initiate acquisition."""
        context = replace(self.context, tools={})
        with patch.object(module, "pin_executable") as pin, patch.object(module, "observe_presenter_asset") as observe:
            with module.acquire_presenter_execution(self.fixture.noop(), context) as owner:
                self.assertIsNone(owner)
        pin.assert_not_called()
        observe.assert_not_called()

    def test_nonblocked_source_or_tool_mutation_invalidates_live_owner(self) -> None:
        """Successful earlier observations cannot keep a changed file usable."""
        for kind in ("source", "tool"):
            fixture = PresenterCaptureFixture()
            self.addCleanup(fixture.close)
            results = [subprocess.CompletedProcess([], 0, raw, "") for raw in fixture.probe.raw()]
            with self.subTest(kind=kind), patch("guided_presenter_observation.run_text", side_effect=results), \
                    self.assertRaisesRegex(RuntimeError, "changed"), \
                    module.acquire_presenter_execution(fixture.inputs, fixture.context) as owner:
                path = fixture.probe.path if kind == "source" else fixture.probe.root / "TEST-ffprobe"
                path.write_bytes(b"changed TEST bytes")
                owner.assert_current()

    def test_plan_context_guard_and_original_expiry_fail_without_new_observation(self) -> None:
        """Guard checks do not turn into more media/source work or refreshed clocks."""
        with patch("guided_presenter_observation.run_text", side_effect=self.results()) as runner, \
                module.acquire_presenter_execution(self.inputs, self.context) as owner:
            old = self.inputs.documents["candidatePlan"]["target"]["width"]
            self.inputs.documents["candidatePlan"]["target"]["width"] = old + 2
            with self.assertRaisesRegex(RuntimeError, "input/context changed"):
                owner.assert_current()
            self.inputs.documents["candidatePlan"]["target"]["width"] = old
            self.fixture.probe.deadline.expired = True
            with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
                owner.assert_current()
            self.fixture.probe.deadline.expired = False
        self.assertEqual(runner.call_count, 2)

    def test_failed_probe_and_cancellation_close_actual_tool_pin(self) -> None:
        """Partial observations and BaseException cannot leak the pinned directory chain."""
        for error in (RuntimeError("TEST failed probe"), KeyboardInterrupt("TEST cancel")):
            with self.subTest(error=type(error).__name__), \
                    patch.object(module, "observe_presenter_asset", side_effect=error), \
                    patch.object(module, "close_pins", wraps=close_pins) as close, \
                    self.assertRaises(type(error)), module.acquire_presenter_execution(self.inputs, self.context):
                self.fail("No owner should have been yielded")
            self.assert_closed(close.call_args.args[0][0])

    def test_tool_hash_failure_closes_before_any_probe(self) -> None:
        """Snapshot metadata alone never substitutes for verifying declared executable bytes."""
        context = replace(self.context, tools={"ffprobe": {**self.context.tools["ffprobe"], "sha256": "f" * 64}})
        with patch.object(module, "close_pins", wraps=close_pins) as close, \
                patch.object(module, "observe_presenter_asset") as observe, self.assertRaisesRegex(RuntimeError, "bytes do not match"):
            with module.acquire_presenter_execution(self.inputs, context):
                self.fail("Wrong tool hash cannot yield an owner")
        observe.assert_not_called()
        self.assert_closed(close.call_args.args[0][0])

    def test_final_hash_callback_expiry_or_late_plan_change_cannot_succeed(self) -> None:
        """Final time/input checks follow the final tool read, not only precede it."""
        original = module.verify_pins
        calls = 0

        def verify(pins: tuple) -> None:
            """Expire only inside the TEST final actual tool verification boundary."""
            nonlocal calls
            calls += 1
            original(pins)
            if calls == 2:
                self.fixture.probe.deadline.expired = True

        with patch.object(module, "verify_pins", side_effect=verify), \
                patch("guided_presenter_observation.run_text", side_effect=self.results()), \
                self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            with module.acquire_presenter_execution(self.inputs, self.context) as owner:
                owner.assert_current()
        with self.assertRaisesRegex(RuntimeError, "lifetime is closed"):
            owner.assert_current()

    def test_plan_change_inside_final_tool_read_is_rejected_and_source_pins_close(self) -> None:
        """Readback checks follow final callbacks, and all source/tool leaf pins close."""
        original_verify, original_pin = module.verify_pins, module.PresenterProbePin
        acquired = []
        calls = 0

        def verify(pins: tuple) -> None:
            """Mutate only the final TEST metadata boundary, after the actual tool hash."""
            nonlocal calls
            calls += 1
            original_verify(pins)
            if calls == 2:
                self.inputs.documents["candidatePlan"]["target"]["width"] += 2

        def pin(*args: object) -> object:
            """Retain TEST references to actual leaf-pin objects for post-exit checks."""
            value = original_pin(*args)
            acquired.append(value)
            return value

        with patch.object(module, "verify_pins", side_effect=verify), \
                patch.object(module, "PresenterProbePin", side_effect=pin), \
                patch("guided_presenter_observation.run_text", side_effect=self.results()), \
                self.assertRaisesRegex(RuntimeError, "input/context changed"):
            with module.acquire_presenter_execution(self.inputs, self.context):
                pass
        self.assertEqual(len(acquired), 2)
        self.assertTrue(all(value.fd == -1 for value in acquired))

    def test_expiry_during_final_descriptor_cleanup_cannot_return_success(self) -> None:
        """Cleanup still completes, but its elapsed time cannot renew successful work."""
        def close(pins: tuple) -> None:
            """Expire the original TEST clock only after closing every real tool FD."""
            close_pins(pins)
            self.fixture.probe.deadline.expired = True

        with patch.object(module, "close_pins", side_effect=close), \
                patch("guided_presenter_observation.run_text", side_effect=self.results()), \
                self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            with module.acquire_presenter_execution(self.inputs, self.context) as owner:
                pass
        with self.assertRaisesRegex(RuntimeError, "lifetime is closed"):
            owner.assert_current()

    def test_under_or_overdeclared_dimensions_reject_after_observation_before_yield(self) -> None:
        """No metadata workload pass is silently promoted over contrary actual probe facts."""
        for width, height in ((32, 18), (128, 72)):
            docs = self.inputs.documents
            docs["manifest"]["broll"][0]["resolution"] = [width, height]
            docs["readinessPacket"]["evidence"]["presenterPolicy"] = guided_presenter_policy(
                docs["acceptedPlan"], docs["manifest"])
            with self.subTest(dimensions=(width, height)), \
                    patch("guided_presenter_observation.run_text", side_effect=self.results()) as runner, \
                    patch.object(module, "close_pins", wraps=close_pins) as close, \
                    self.assertRaisesRegex(RuntimeError, "observed dimensions differ"), \
                    module.acquire_presenter_execution(self.inputs, self.context):
                self.fail("Mismatched dimensions cannot yield an owner")
            self.assertEqual(runner.call_count, 2)
            self.assert_closed(close.call_args.args[0][0])


if __name__ == "__main__":
    unittest.main()
