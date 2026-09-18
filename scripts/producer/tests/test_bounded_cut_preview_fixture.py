"""No-media tests for the fixed TEST source-generator deadline adapter."""
from pathlib import Path
import unittest
from unittest.mock import patch

import _bounded_cut_preview_fixture as adapter


class BoundedFixtureTests(unittest.TestCase):
    def test_expired_invalid_and_future_clocks_fail_before_generator(self) -> None:
        """An invalid original expiry never launches even stub work."""
        for expiry in (0, 1_000_000_000, 62_000_000_000):
            with (patch.object(adapter.time, "monotonic_ns", return_value=1_000_000_000),
                  patch.object(adapter.fixture, "main") as generated,
                  self.assertRaisesRegex(RuntimeError, "expired/invalid")):
                adapter.run_fixture(Path("/TEST"), "160x90", adapter.LocalDeadline(expiry))
            generated.assert_not_called()

    def test_original_work_receives_only_tighter_remaining_timeout(self) -> None:
        """No invented outputs: the existing FFmpeg function receives real args."""
        seen = []

        def generate() -> None:
            adapter.fixture.ffmpeg(["TEST-argument"], 20)

        with (patch.object(adapter.time, "monotonic_ns", return_value=1_000_000_000),
              patch.object(adapter.fixture, "ffmpeg", side_effect=lambda args, timeout: seen.append((args, timeout))),
              patch.object(adapter.fixture, "main", side_effect=generate)):
            adapter.run_fixture(Path("/TEST"), "160x90", adapter.LocalDeadline(3_000_000_000))
        self.assertEqual(seen, [(["TEST-argument"], 2.0)])


if __name__ == "__main__":
    unittest.main()
