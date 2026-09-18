"""TEST-only lifecycle leaves: no Docker, decoder, actual observation or approval.

The real claim reader has separate file-based tests. This suite replaces ONLY
that boundary and native leaves to test the shared policy's ordering, original
clock, retained failure and unconditional exact cleanup behavior.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from color.grade_observation_profile import V2
from headless import grade_observation_policy as policy
from _grade_launch_fixture import GradeLaunchFixture

SHA = "a" * 64
NAME = "sniper-grade-observation-" + "b" * 32
REFERENCE = "c" * 64
REQUEST = {"sourceSha256": SHA, "frameCount": 180, "timeoutSeconds": 120}


class TestHeldLaunch:
    """Explicit TEST substitute for file-bound ownership; not a production handle."""

    def __init__(self, events: list, fail: str | None = None) -> None:
        """Keep one actual original cutoff and an event-specific fault."""
        self.name = NAME
        self.deadline = time.monotonic() + 300
        self.events, self.fail = events, fail

    def check(self) -> None:
        """Record the private policy check, with no invented media authority."""
        self.events.append("check")
        if self.fail == "check":
            raise RuntimeError("TEST original ownership changed")

    def before_launch(self, runtime: object, command: list[str]) -> str:
        """Simulate the separate durable-intent boundary, never a Docker call."""
        self.events.append("intent")
        if self.fail == "intent":
            raise RuntimeError("TEST intent publication failed")
        return "d" * 64

    def after_launch(self, reference: str) -> None:
        """Fault after actual policy launch return so its finally must still run."""
        self.events.append("response")
        if self.fail == "response":
            raise RuntimeError("TEST response publication failed")


class PolicyFixture:
    """Own only explicit generated source/attempt files below one TEST root."""

    def __init__(self, root: Path, fail: str | None = None) -> None:
        """Create inert source bytes and a private empty execution directory."""
        self.source, self.attempt = root / "TEST-source.bin", root / "execution"
        self.source.write_bytes(b"TEST inert input; not a media observation")
        self.attempt.mkdir(mode=0o700)
        self.events: list[str] = []
        self.held = TestHeldLaunch(self.events, fail)
        self.owner = policy.OwnedGradeLaunch(root / "TEST-unread-claim.json", SHA, self.held.deadline, lambda: None)
        self.on_hold = lambda: None
        self.fail = fail
        self.launch_args: list[tuple] = []
        self.cleanup_refs: list[str] = []

    def launch(self, runtime: object, directory: str, command: list, name: str) -> str:
        """TEST native-launch leaf retaining exact requested arguments only."""
        self.events.append("launch")
        self.launch_args.append((directory, list(command), name))
        if self.fail == "launch":
            raise RuntimeError("TEST lost launch response")
        return REFERENCE

    def reconcile(self, runtime: object, directory: str, name: str) -> None:
        """TEST daemon reconciliation leaf; no actual resource is created/deleted."""
        self.events.append("reconcile")
        self.cleanup_refs.append(name)

    def remove(self, runtime: object, directory: str, reference: str) -> dict:
        """TEST exact absence leaf, optionally returning an ambiguous result."""
        self.events.append("remove")
        self.cleanup_refs.append(reference)
        return {"canonicalAbsenceProved": self.fail != "cleanup"}

    def hold(self, owner: object, source: str, request: dict, directory: Path) -> TestHeldLaunch:
        """Optional virtual preparation delay at the explicitly replaced file-read boundary."""
        self.on_hold()
        return self.held

    def install(self, stack: ExitStack, request: dict) -> None:
        """Replace named IO leaves, not the shared launch/finally/publication flow."""
        profile = policy.observation_profile(request.get("profile"))
        defaults = {"required_runtime": object(), "_launch_command": (["TEST-fixed-command"], SHA),
            "implementation_sources": [], "file_hash": SHA, "attest_image": {"Id": "sha256:" + SHA},
            "attest_probe_container": {}, "probe_container": {},
            "_wait": {"status": "complete", "request": request, "policy": profile.policy}}
        for name, value in defaults.items():
            stack.enter_context(patch.object(policy, name, return_value=value))
        stack.enter_context(patch.object(policy, "hold_grade_launch", side_effect=self.hold))
        for name, function in (("_launch", self.launch), ("reconcile_launch_abort", self.reconcile), ("remove_container", self.remove)):
            stack.enter_context(patch.object(policy, name, side_effect=function))

    def run(self, request: dict | None = None) -> dict:
        """Execute actual shared policy with the explicitly stubbed owner/native leaves."""
        request = REQUEST if request is None else request
        with ExitStack() as stack:
            self.install(stack, request)
            return policy.run_owned_isolated_grade(str(self.source), request, self.attempt, self.owner)


class OwnedGradeLaunchPolicyTests(unittest.TestCase):
    """A durable intent precedes launch, while every launched path retains cleanup."""

    def test_exact_name_intent_order_original_deadline_and_private_flags(self) -> None:
        """New naming must not alter request limits or gain grade/release approval."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PolicyFixture(Path(temporary).resolve())
            result = fixture.run()
            self.assertEqual(fixture.launch_args, [(str(fixture.attempt), ["TEST-fixed-command"], NAME)])
            self.assertLess(fixture.events.index("intent"), fixture.events.index("launch"))
            self.assertLess(fixture.events.index("response"), fixture.events.index("remove"))
            self.assertEqual(fixture.cleanup_refs, [REFERENCE])
            self.assertLessEqual(int(result["workDeadlineMonotonicNs"]) / 1e9, fixture.held.deadline)
            self.assertEqual(result["request"], REQUEST)
            self.assertIs(result["gradeApplicable"], False)
            self.assertIs(result["deliveryApproved"], False)
            self.assertEqual(result["launchIntentSha256"], "d" * 64)

    def assert_failure(self, stage: str, cleanup: bool) -> None:
        """Reuse exact named TEST fixture roots; never choose a dependency to mutate."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PolicyFixture(Path(temporary).resolve(), stage)
            with self.assertRaises(policy.GradeIsolationError) as raised:
                fixture.run()
            result = raised.exception.evidence
            self.assertIs(result["cleanupVerified"], cleanup)
            self.assertEqual(result["status"], "failed")
            self.assertIs(result["gradeApplicable"], False)
            self.assertTrue((fixture.attempt / "execution.json").is_file())
            self.assertEqual(fixture.source.read_bytes(), b"TEST inert input; not a media observation")
            if stage in {"launch", "response", "intent"}:
                self.assertEqual(fixture.cleanup_refs, [NAME, NAME])
            if stage in {"check", "intent"}:
                self.assertNotIn("launch", fixture.events)

    def test_lost_launch_response_reconciles_exact_preclaimed_name(self) -> None:
        """No returned ID is not evidence that Docker created nothing."""
        self.assert_failure("launch", True)

    def test_after_launch_publication_failure_still_reconciles(self) -> None:
        """The post-launch hook remains inside the original unconditional finally."""
        self.assert_failure("response", True)

    def test_prelaunch_publication_failure_never_calls_launch(self) -> None:
        """Only exact cleanup, not the lack of an ID, settles a preclaimed resource."""
        self.assert_failure("intent", True)

    def test_owner_failure_before_runtime_retains_unobserved_claim(self) -> None:
        """Owned prelaunch failures do not inherit legacy no-random-resource evidence."""
        self.assert_failure("check", False)

    def test_ambiguous_cleanup_never_becomes_success(self) -> None:
        """All output remains private failed evidence when absence is unproved."""
        self.assert_failure("cleanup", False)

    def test_explicit_v2_keeps_profile_and_original_shorter_deadline(self) -> None:
        """No v2 request can replace an already shorter owner deadline."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PolicyFixture(Path(temporary).resolve())
            request = {**REQUEST, "schemaVersion": 2, "profile": V2.token, "timeoutSeconds": 1200}
            result = fixture.run(request)
            self.assertEqual(result["profile"], V2.token)
            self.assertEqual(result["limits"], V2.evidence()["limits"])
            self.assertLessEqual(int(result["workDeadlineMonotonicNs"]) / 1e9, fixture.held.deadline)

    def test_replay_does_not_replace_prior_attempt_or_launch_again(self) -> None:
        """The unchanged empty-private-directory requirement rejects the second call."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PolicyFixture(Path(temporary).resolve())
            fixture.run()
            with self.assertRaisesRegex(RuntimeError, "empty private"):
                fixture.run()
            self.assertEqual(fixture.events.count("launch"), 1)

    def test_publication_cannot_escape_effective_phase_into_longer_owner_clock(self) -> None:
        """Virtual time crosses the V1 120s cap during actual TEST file publication."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            fixture = PolicyFixture(Path(temporary).resolve())
            now = [time.monotonic()]
            original = policy.write_new
            def delayed_write(path: Path, value: dict) -> None:
                """Advance only virtual time after writing the exact owned fixture result."""
                self.assertEqual(path, fixture.attempt / "execution.json")
                original(path, value)
                now[0] += 121
            stack.enter_context(patch.object(policy.time, "monotonic", side_effect=lambda: now[0]))
            stack.enter_context(patch.object(policy, "write_new", side_effect=delayed_write))
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                fixture.run()
            self.assertLess(now[0], fixture.held.deadline)
            self.assertEqual(fixture.cleanup_refs, [REFERENCE])
            self.assertTrue((fixture.attempt / "execution.json").exists())

    def test_preclaim_acquisition_consumes_the_same_request_phase(self) -> None:
        """Metadata hold time is not free or a reason to restart the 120s request cap."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PolicyFixture(Path(temporary).resolve())
            started = time.monotonic()
            now = [started]
            def hold_delay() -> None:
                """Advance only the fixture's virtual clock, with no sleeping or IO."""
                now[0] += 20
            fixture.on_hold = hold_delay
            with patch.object(policy.time, "monotonic", side_effect=lambda: now[0]):
                result = fixture.run()
            self.assertLessEqual(int(result["workDeadlineMonotonicNs"]) / 1e9, started + 120)
            self.assertGreater(int(result["workDeadlineMonotonicNs"]) / 1e9, started + 119)

    def test_real_preclaim_files_feed_shared_policy_with_only_native_leaves_stubbed(self) -> None:
        """Exercise actual source hashes/claim/argv/publications, NOT a real native observation."""
        fixture = GradeLaunchFixture()
        self.addCleanup(fixture.close)
        defaults = {"required_runtime": fixture.runtime, "attest_image": {"Id": fixture.runtime.image_id},
            "_launch": REFERENCE, "attest_probe_container": {}, "probe_container": {},
            "_wait": {"status": "complete", "request": fixture.request, "policy": policy.POLICY},
            "remove_container": {"canonicalAbsenceProved": True}, "reconcile_launch_abort": None}
        with ExitStack() as stack:
            for name, value in defaults.items():
                stack.enter_context(patch.object(policy, name, return_value=value))
            result = policy.run_owned_isolated_grade(str(fixture.source), fixture.request, fixture.directory, fixture.owner)
        intent_path = fixture.directory / "launch-intent.json"
        self.assertEqual(result["launchIntentSha256"], policy.file_hash(intent_path))
        self.assertEqual(result["sourceBeforeSha256"], fixture.request["sourceSha256"])
        self.assertEqual(result["sourceAfterSha256"], fixture.request["sourceSha256"])
        self.assertTrue((fixture.directory / "launch-response.json").is_file())
        self.assertIs(result["gradeApplicable"], False)
        self.assertIs(result["deliveryApproved"], False)


if __name__ == "__main__":
    unittest.main()
