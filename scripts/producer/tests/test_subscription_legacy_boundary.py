"""No-provider tests for explicitly unsupported legacy automatic invocations."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import live_desktop_palmier_first60_acceptance as desktop
import live_headless_claude_mcp_smoke as headless
from study import deep_semantics


class SubscriptionLegacyBoundaryTests(unittest.TestCase):
    """Unknown auth must fail before provider calls or successful evidence."""

    def test_semantics_default_fails_before_frames_and_never_reports_ran(self) -> None:
        """Requested semantics cannot silently degrade to a successful study."""
        with patch("subprocess.run") as run, patch.object(deep_semantics, "event_frames") as frames:
            with self.assertRaisesRegex(RuntimeError, "Subscription admission not qualified"):
                deep_semantics.run_semantics("unused", None, [], "unused")
            run.assert_not_called()
            frames.assert_not_called()

    def test_direct_default_semantics_spawn_is_also_blocked(self) -> None:
        """Calling the low-level seam cannot bypass the entrypoint guard."""
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "No semantic analysis ran"):
                deep_semantics._default_spawn("TEST ONLY")
            run.assert_not_called()

    def test_headless_harness_does_not_spawn_provider(self) -> None:
        """The optional live harness is not a backdoor to ambient credentials."""
        with patch("subprocess.run") as run, patch("subprocess.Popen") as spawn:
            with self.assertRaisesRegex(headless.PalmierError, "Subscription admission not qualified"):
                headless._run_claude("TEST ONLY", "unused", False)
            run.assert_not_called()
            spawn.assert_not_called()

    def test_desktop_harness_does_not_spawn_or_touch_session(self) -> None:
        """A failure neither reads nor marks a local editing session started."""
        with patch("subprocess.Popen") as spawn, patch.object(desktop, "_read") as read:
            with self.assertRaisesRegex(desktop.PalmierError, "Subscription admission not qualified"):
                desktop.claude("plan")
            spawn.assert_not_called()
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
