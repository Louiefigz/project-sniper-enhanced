"""Mixed engines on one pool, continued (X242): an uncovered request fails closed beside an older client's member.

M-057 makes an uncovered request (a Long no profile covers) wait for an idle pool beside this engine's live members.
An older (4a15560) client predates that wait, so beside one of its live members the request is refused at once by
name, never queued or credited, even when a member of this engine is live too. The base client runs from
tests/fixtures/base_pool_driver.py in a private TEST namespace with a TEST schema-1 record
(``test_native_work_pool_mixed_engine``'s set-up and helpers, reused); nothing reads the host pool.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest

from native_work_pool_fence import NativeWorkUnsupportedMix
from native_work_pool_state import NativeWorkQueued
from _native_pool_fixture import BasePoolClient
import test_native_work_pool_mixed_engine as mixed   # its set-up and helpers, never its tests


class MixedOwnersTests(BasePoolClient, unittest.TestCase):
    """A live member of each engine: the older one decides; alone, this engine's member makes the Long wait."""

    def setUp(self) -> None:
        """``MixedEngineTests``' private namespace, TEST schema-1 record (3 heavy, 1 audio), Short and Long."""
        mixed.MixedEngineTests.setUp(self)

    def acquire(self, project: str) -> object:
        """Admit a heavy member of this engine in this process (``MixedEngineTests.acquire``)."""
        return mixed.MixedEngineTests.acquire_lane(self, 'heavy', project)

    def test_an_older_member_beside_a_same_engine_member_fails_closed_by_name(self) -> None:
        """Older member and this engine's Short both live: the Long is refused naming the older member only; once
        the older member ends, the same-engine member alone makes the Long wait as a queued ticket."""
        holder = mixed.MixedEngineTests.older_member(self)
        short = self.acquire(self.short)
        with self.assertRaisesRegex(NativeWorkUnsupportedMix, r"an older pool client's member\(s\) \S+ are live: it "
                                                              'cannot wait beside them') as refused:
            self.acquire(self.long)
        self.assertNotIn(short.nonce, str(refused.exception))
        mixed.MixedEngineTests.release(self, holder)
        with self.assertRaisesRegex(NativeWorkQueued, f'an uncovered workload waits for an idle pool: .*live '
                                                      f'members: {short.nonce}'):
            self.acquire(self.long)
        short.complete()


if __name__ == '__main__':
    unittest.main()
