"""Mixed Long/Short (M1): the pool's mix refusal is a waitable ticket in both directions.

The pool and the owner admission loop (studio.native_run_admission.join_queue and
attempt_pool_admission) are real, in a private namespace. Only the owner is a TEST stand-in, and the
loop's clock and sleep are fake: each fake sleep advances the clock and lets the scheduled holder finish
(probe_la06.py's cases A, B and C, without real waiting or threads). Records: a TEST Short-only schema-2
profile (three heavy slots), or a TEST schema-1 record where audio must be covered (legacy-v1). X107's
rules are here too: a self-conflict is refused at once (m1), and audio passes a waiting uncovered ticket
at most PASS_LIMIT times while a live member's own work always does (m2).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_mix as mix
from native_render_resources import GIB
from native_work_pool_fence import NativeWorkUnsupportedMix
from native_work_pool_policy import STUDIO_CLASS
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from studio import native_run_admission as admission
from _native_pool_fixture import (
    fixture_profile, isolate_pool, plan_project, qualify_fixture_host, qualify_fixture_profiles,
)

SLOTS = {'heavy': 3, 'audio': 1}


class FakeClock:
    """Admission's monotonic clock; it advances only when admission sleeps, and each sleep runs one release."""

    def __init__(self, releases: list[Callable[[], None]]) -> None:
        """Start at a fixed TEST time with the holders to release, in order."""
        self.now, self.releases, self.sleeps = 1000.0, list(releases), 0

    def monotonic(self) -> float:
        """The fake time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake time and let the next scheduled holder finish."""
        self.sleeps += 1
        self.now += seconds
        if self.releases:
            self.releases.pop(0)()


def owner_for(project: Path, stage: str = 'pipeline') -> SimpleNamespace:
    """A TEST owner exposing what join_queue and attempt_pool_admission read (probe_la06.owner_for)."""
    return SimpleNamespace(settings=SimpleNamespace(lane='heavy', policy=None, disk_reservation_bytes=None),
                           project=project, root=project, path=project / f'{stage}.render.json', result={},
                           lease=None, capacity_context=None, supporting_contexts=[], capacity_credit=0.0,
                           capacity_wait_started=None, deadline=3600.0, abort_reason=None, hard_deadline=None,
                           persist=lambda: None)


class MixWaitTests(unittest.TestCase):
    """Real admission of Shorts beside Longs, and the requests a waiting exclusive ticket lets pass."""

    def setUp(self) -> None:
        """Private namespace, two TEST Short projects and one TEST Long project."""
        self.root = isolate_pool(self)
        self.shorts = [plan_project(self, 'short', 45.0) for _ in range(2)]
        self.long = plan_project(self, 'long', 600.0)

    def request(self, project: Path, stage: str = 'pipeline', lane: str = 'heavy') -> pool.PoolRequest:
        """One owner's request, kept across attempts and withdrawn at cleanup."""
        request = pool.PoolRequest(lane, str(project), root=str(project), declares_launch=True,
                                   receipt=str(project / f'{stage}.render.json'))
        self.addCleanup(request.withdraw)
        return request

    def admit(self, request: pool.PoolRequest) -> object:
        """Admit now through the public entry point; closed at cleanup."""
        lease = work.NativeWorkLease.acquire(request.lane, request.project, request=request)
        self.addCleanup(lease.close)
        return lease

    def refusal(self, request: pool.PoolRequest, kind: type = NativeWorkQueued) -> Exception:
        """The refusal this request gets now (its ticket is kept)."""
        with self.assertRaises(kind) as caught:
            work.NativeWorkLease.acquire(request.lane, request.project, request=request)
        return caught.exception

    def join(self, owner: SimpleNamespace, releases: list[Callable[[], None]]) -> FakeClock:
        """Run the real owner admission loop with the fake clock (60 TEST seconds of patience)."""
        clock = FakeClock(releases)
        with mock.patch.object(admission, 'time', clock), mock.patch('builtins.print'):
            admission.join_queue(owner, clock.monotonic() + 60.0)
        self.addCleanup(owner.lease.close)
        return clock

    def assert_waited_then_admitted(self, owner: SimpleNamespace, clock: FakeClock, mode: str) -> None:
        """Admitted after at least one wait, in the given mode, with no failure category."""
        self.assertEqual(owner.lease.admission['mode'], mode)
        self.assertGreaterEqual(owner.result['queue']['attempts'], 2)
        self.assertEqual((owner.result['queue']['admitted'], clock.sleeps >= 1), (True, True))
        self.assertNotIn('failureCategory', owner.result)

    def test_short_behind_live_exclusive_long_waits_then_is_admitted(self) -> None:
        """Probe case A: the Short waits beside the live exclusive Long and runs once the Long ends."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        long = self.admit(self.request(self.long))
        owner = owner_for(self.shorts[0])
        self.assert_waited_then_admitted(owner, self.join(owner, [long.complete]), 'qualified')

    def test_long_behind_live_short_waits_then_is_admitted(self) -> None:
        """Probe case C: the uncovered Long waits for an idle pool and then runs alone."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        short = self.admit(self.request(self.shorts[0]))
        owner = owner_for(self.long)
        self.assert_waited_then_admitted(owner, self.join(owner, [short.complete]), 'exclusive')
        self.assertEqual(owner.lease.reservation_bytes, 16 * GIB)

    def test_capacity_wait_is_unchanged(self) -> None:
        """Probe case B: a fourth Short waits for a full pool's slot as before."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        holders = [self.admit(self.request(self.shorts[0])) for _ in range(3)]
        owner = owner_for(self.shorts[1])
        self.assert_waited_then_admitted(owner, self.join(owner, [holders[0].complete]), 'qualified')
        self.assertIn('all 3 heavy slot(s) are occupied', owner.result['admissionReasons'][0])

    def test_short_behind_live_long_is_capacity_only(self) -> None:
        """The live Long occupies what the Short needs: the mix wait is credited, the Long is its occupant."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        long = self.admit(self.request(self.long))
        error = self.refusal(self.request(self.shorts[0]))
        self.assertIn('already active: waiting for member(s) ' + long.nonce, str(error))
        self.assertIs(error.capacity_only, True)
        self.assertEqual((error.capacity_evidence['occupants'], error.capacity_evidence['waitClass']),
                         ([long.nonce], 'capacity'))

    def test_short_behind_a_pool_draining_for_a_queued_long_is_not_credited(self) -> None:
        """Live slots are free while the pool drains for a queued Long: a queue-order wait, uncredited."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        self.admit(self.request(self.shorts[0]))
        self.refusal(self.request(self.long))  # waits for an idle pool, keeping its ticket
        error = self.refusal(self.request(self.shorts[1]))
        self.assertIn('queued behind 1 earlier request(s)', str(error))
        self.assertEqual((error.capacity_only, error.capacity_evidence['waitClass']), (False, 'other'))

    def test_audio_request_passes_a_waiting_exclusive_ticket(self) -> None:
        """An audio owner, even for a project no member runs, is never held back by the waiting Long."""
        qualify_fixture_host(self, SLOTS)
        self.admit(self.request(self.shorts[0]))
        self.refusal(self.request(self.long))
        self.admit(self.request(self.shorts[1], 'audio-stage', 'audio')).complete()

    def test_same_project_request_passes_a_waiting_exclusive_ticket(self) -> None:
        """A render of a live member's project (possible nested work) is never held back by the waiting Long."""
        qualify_fixture_host(self, SLOTS)
        self.admit(self.request(self.shorts[0]))
        self.refusal(self.request(self.long))
        self.admit(self.request(self.shorts[0], 'capture')).complete()
        self.assertIn('queued behind 1', str(self.refusal(self.request(self.shorts[1]))))  # another project waits

    def test_uncovered_request_beside_its_own_projects_member_is_refused_at_once(self) -> None:
        """An uncovered stage beside its own project's live member can never run: refused, no ticket left."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        self.admit(self.request(self.shorts[0]))
        owner = owner_for(self.shorts[0], 'preview-picture-4')  # a stage the Short profile never exercised
        with self.assertRaisesRegex(NativeWorkUnsupportedMix, "its own project's member .* is live"):
            with mock.patch.object(admission, 'time', FakeClock([])), mock.patch('builtins.print'):
                admission.join_queue(owner, 1060.0)
        self.assertEqual((owner.result['failureCategory'], owner.result['queue']['attempts']),
                         ('pool-unsupported-mix', 1))
        self.admit(self.request(self.shorts[1])).complete()  # nothing was left queued ahead of it

    def test_a_covered_stage_beside_its_own_projects_exclusive_member_is_refused_at_once(self) -> None:
        """m1 (X107): a self-conflict never resolves by waiting: refused by name, never queued or credited."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        parent = self.admit(self.request(self.shorts[0], 'preview-picture-4'))  # an unexercised stage: exclusive
        self.assertEqual(parent.admission['mode'], 'exclusive')
        error = self.refusal(self.request(self.shorts[0]), NativeWorkUnsupportedMix)
        self.assertIn(f"its own project's member(s) {parent.nonce} run exclusive", str(error))
        self.assertNotIn('already active', str(error))
        self.assertIn('waiting for member(s)', str(self.refusal(self.request(self.shorts[1]))))  # others wait

    def test_a_stream_of_audio_cannot_starve_an_uncovered_long(self) -> None:
        """m2 (X107): audio passes a waiting uncovered Long PASS_LIMIT times, then queues; nested work passes."""
        qualify_fixture_host(self, SLOTS)
        holder = self.admit(self.request(self.shorts[0]))
        long = self.request(self.long)
        self.refusal(long)
        for _ in range(mix.PASS_LIMIT):
            audio = self.admit(self.request(plan_project(self, 'short', 45.0), 'audio-stage', 'audio'))
            self.refusal(long)  # the Long sees the member that passed it
            audio.complete()
        ticket = json.loads((self.root / 'pool-v1' / long.ticket.name).read_text())
        self.assertEqual(len(ticket['passedBy']), mix.PASS_LIMIT)
        late = self.request(plan_project(self, 'short', 45.0), 'audio-stage', 'audio')
        self.assertIn('queued behind 1 earlier request(s)', str(self.refusal(late)))  # FIFO holds now
        self.admit(self.request(self.shorts[0], 'capture')).complete()  # the live Short's own work still passes
        holder.complete()
        self.admit(long).complete()
        self.admit(late).complete()

    def test_an_uncovered_request_waits_beside_its_own_projects_studio_start(self) -> None:
        """A Studio start takes part in no mix decision: the Long waits for its slot, never refused at once."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        self.admit(self.request(self.long, lane=STUDIO_CLASS))  # the Long's own Studio view starting
        self.assertIn('all 1 heavy slot(s) are occupied', str(self.refusal(self.request(self.long))))

    def test_a_quarantined_member_of_its_own_project_never_refuses_at_once(self) -> None:
        """Only a live own-project member makes an uncovered stage unsupported; a quarantined one is capacity."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        self.admit(self.request(self.shorts[0])).close()  # quarantined
        self.admit(self.request(self.shorts[1]))
        self.refusal(self.request(self.shorts[0], 'preview-picture-4'), NativeWorkQuarantined)

    def test_a_quarantined_members_project_never_passes_a_waiting_long(self) -> None:
        """Only a live member's project is possible nested work: a quarantined member's project queues behind X."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        first = self.admit(self.request(self.shorts[0]))
        self.admit(self.request(self.shorts[1]))
        self.refusal(self.request(self.long))  # X waits for the live Shorts, keeping its ticket
        first.close()  # quarantined after X queued
        self.assertIn('queued behind 1', str(self.refusal(self.request(self.shorts[0], 'capture'))))

    def test_quarantined_exclusive_member_stays_terminal(self) -> None:
        """An exclusive Long closed without verified cleanup keeps its exclusivity: the Short must not wait."""
        qualify_fixture_profiles(self, [fixture_profile(SLOTS)])
        self.admit(self.request(self.long)).close()
        error = self.refusal(self.request(self.shorts[0]), NativeWorkQuarantined)
        self.assertIn('outside qualification profile', str(error))
        self.assertIn('unverified cleanup', str(error))


if __name__ == '__main__':
    unittest.main()
