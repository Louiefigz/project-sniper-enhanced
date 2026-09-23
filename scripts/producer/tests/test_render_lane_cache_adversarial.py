"""Retained cache identity/read checks without executing retired R0 overlays."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest import mock

from _render_result_fixture import CONTAINER_NAME, HistoricalResultFixture
from headless.render_lane_cache import CacheOwnershipError, prepare_attempt_cache


class RenderLaneCacheAdversarialTests(HistoricalResultFixture):
    """Historical cached proof still requires owned bytes and prior removal."""

    def test_cached_result_accepts_only_prior_removed_container_proof(self) -> None:
        value = self._value()
        first, _ = self._validate(value)
        self.assertFalse(first["cached"])
        value["cached"] = True
        with mock.patch("headless.render_lane.removed_containers",
                        return_value=(CONTAINER_NAME,)):
            second, _ = self._validate(value)
        self.assertTrue(second["cached"])
        with mock.patch("headless.render_lane.removed_containers", return_value=()):
            with self.assertRaisesRegex(RuntimeError, "registered resource"):
                self._validate(value)

    def test_symlink_and_wrong_mode_cache_fail_closed(self) -> None:
        alias = self.root / "attempt-alias"
        alias.symlink_to(self.attempt, target_is_directory=True)
        with self.assertRaisesRegex(CacheOwnershipError, "symlink-free"):
            prepare_attempt_cache(str(alias), self.identity)
        os.chmod(self.binding.cache_dir, 0o755)
        with self.assertRaisesRegex(CacheOwnershipError, "0700"):
            prepare_attempt_cache(str(self.attempt), self.identity)

    def test_restrictive_umask_cannot_weaken_new_cache_receipt(self) -> None:
        attempt = self.root / "umask-attempt"
        attempt.mkdir(mode=0o700)
        os.chmod(attempt, 0o700)
        identity = ("umask-attempt", *self.identity[1:])
        previous = os.umask(0o777)
        try:
            binding = prepare_attempt_cache(str(attempt), identity)
        finally:
            os.umask(previous)
        owner = Path(binding.cache_dir) / ".owner.json"
        self.assertEqual(stat.S_IMODE(owner.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(binding.cache_dir).stat().st_mode), 0o700)
        self.assertEqual(prepare_attempt_cache(str(attempt), identity), binding)
