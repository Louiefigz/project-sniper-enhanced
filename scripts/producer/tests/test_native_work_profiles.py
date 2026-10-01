"""Qualification profiles: record validation, selection and consumption at real pool admission.

Records are TEST-labelled fixtures for a TEST host and (unless a test says otherwise) a
TEST engine identity, written to temporary folders; the pool namespace is private. One
test computes the real engine identity of this checkout to prove the binding end to end.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import native_work_lease as work
import native_work_pool as pool
import native_work_profiles as profiles
import native_work_qualification as qualification
import native_work_workload as workloads
from native_render_resources import GIB
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from _native_pool_fixture import (
    SHORT_PIXELS, TEST_ENGINE, TEST_HOST, fixture_job, fixture_profile, isolate_pool,
    plan_project, qualify_fixture_host, qualify_fixture_profiles,
)

SHORT_SLOTS = {'heavy': 3, 'audio': 1}


def workload(**values: object) -> dict:
    """A Short render owner on the TEST engine; override any field."""
    return {'format': 'short', 'stage': 'pipeline', 'class': 'heavy', 'durationSeconds': 45.0,
            'pixels': SHORT_PIXELS, 'cache': 'unobserved', 'engine': TEST_ENGINE['identity'], **values}


def long_profile() -> dict:
    """A TEST Long-only profile: two heavy slots, 900 s at 1920x1080."""
    jobs = [fixture_job(index, format='long', durationSeconds=900.0, pixels=1920 * 1080) for index in range(2)]
    return fixture_profile({'heavy': 2, 'audio': 1}, jobs)


class ProfileRecordTests(unittest.TestCase):
    """Schema-2 validation: bounds come from evidence, mixed claims need real audio overlap."""

    def validate(self, profile: dict) -> dict:
        """Validate one TEST profile for the 64 GiB TEST host."""
        return profiles.validate_profile(profile, TEST_HOST['memsizeBytes'])

    def test_heavy_only_or_prepared_audio_evidence_cannot_claim_mixed(self) -> None:
        """A mixed claim needs the jobs' own audio stage overlapping heavy owners."""
        heavy_only = fixture_profile(SHORT_SLOTS, class_mix='mixed')
        with self.assertRaisesRegex(profiles.PoolRecordError, 'only heavy owners or prepared audio'):
            self.validate(heavy_only)
        packaging = {'jobsWithHeavyPeak': 3, 'heavyOwnersPeak': 3, 'audioOwnersPeak': 1, 'audioWithHeavyPeak': 1,
                     'audioStageWithHeavyPeak': 0}
        with self.assertRaisesRegex(profiles.PoolRecordError, 'no job ran its own audio stage'):
            self.validate(fixture_profile(SHORT_SLOTS, class_mix='mixed', evidence={'overlap': packaging}))
        jobs = [fixture_job(0, ownAudioStage=True, stages=['audio-stage', 'pipeline']), fixture_job(1), fixture_job(2)]
        for overlap in (None, packaging):  # own stage never beside heavy work; only packaging was
            with self.subTest(overlap=overlap), self.assertRaisesRegex(profiles.PoolRecordError,
                                                                       'audio-stage owners never overlapped'):
                self.validate(fixture_profile(SHORT_SLOTS, jobs, 'mixed', overlap and {'overlap': overlap}))
        mixed = fixture_profile(SHORT_SLOTS, jobs, 'mixed', {'overlap': dict(packaging, audioStageWithHeavyPeak=1)})
        usable = self.validate(mixed)
        self.assertEqual(profiles.mismatches(usable, workload(stage='audio-stage', **{'class': 'audio'})), [])
        self.assertIn('audio owners are outside the heavy-only class mix',
                      profiles.mismatches(self.validate(fixture_profile(SHORT_SLOTS)),
                                          workload(**{'class': 'audio'})))

    def test_bounds_metrics_failures_and_cleanup_must_match_evidence(self) -> None:
        """A record cannot claim wider bounds, missing metrics, failures or unverified cleanup."""
        cases = [('workload', lambda value: dict(value, formats={'short': dict(value['formats']['short'],
                                                                                  maxDurationSeconds=600.0)}),
                  'bounds differ'),
                 ('evidence', lambda value: {key: item for key, item in value.items() if key != 'cpu'},
                  'cpu metrics are incomplete'),
                 ('evidence', lambda value: dict(value, failures={'failedJobs': 1, 'failedOwners': 0}),
                  'recorded failures'),
                 ('evidence', lambda value: dict(value, cleanup={'owners': 12, 'unverifiedOwners': 1}),
                  'verified cleanup'),
                 ('engine', lambda value: {'identity': 'TEST', 'files': 1}, 'engine identity is invalid')]
        for key, change, message in cases:
            profile = fixture_profile(SHORT_SLOTS)
            profile[key] = change(profile[key])
            with self.subTest(message=message), self.assertRaisesRegex(profiles.PoolRecordError, message):
                self.validate(profile)
        uncached = fixture_profile(SHORT_SLOTS, [fixture_job(index, cacheState=None) for index in range(3)])
        with self.assertRaisesRegex(profiles.PoolRecordError, 'source-cache state'):
            self.validate(uncached)

    def test_short_only_profile_never_covers_a_long(self) -> None:
        """Format, duration, picture size and stage are exercised bounds, never widened."""
        usable = self.validate(fixture_profile(SHORT_SLOTS))
        self.assertEqual(profiles.mismatches(usable, workload()), [])
        self.assertEqual(profiles.mismatches(usable, workload(stage=workloads.stage_label('preview-picture-3'))),
                         ['stage preview-picture was not exercised'])
        long = workload(format='long', durationSeconds=600.0, pixels=1920 * 1080)
        self.assertIn('format long was not exercised (short)', profiles.mismatches(usable, long))
        self.assertEqual(profiles.mismatches(usable, workload(durationSeconds=61.0)),
                         ['output seconds 61.0 exceed the exercised 60.0'])
        self.assertEqual(profiles.mismatches(usable, workload(durationSeconds=None)),
                         ['output seconds are unknown; the profile is bounded at 60.0'])
        self.assertIn('format unbound was not exercised (short)',
                      profiles.mismatches(usable, workload(format='unbound')))

    def test_bounds_are_per_format_in_a_mixed_format_profile(self) -> None:
        """A Long's 900 s never lets a Short run 600 s; each format keeps its own exercised bounds."""
        jobs = [fixture_job(0, format='long', durationSeconds=900.0, pixels=1920 * 1080,
                            stages=['capture', 'pipeline', 'verification']), fixture_job(1, durationSeconds=45.0),
                fixture_job(2, durationSeconds=45.0)]
        usable = self.validate(fixture_profile(SHORT_SLOTS, jobs))
        self.assertEqual(sorted(usable['workload']['formats']), ['long', 'short'])
        self.assertEqual(profiles.mismatches(usable, workload(format='long', durationSeconds=900.0,
                                                              pixels=1920 * 1080)), [])
        self.assertEqual(profiles.mismatches(usable, workload(durationSeconds=600.0)),
                         ['output seconds 600.0 exceed the exercised 45.0'])
        self.assertEqual(profiles.mismatches(usable, workload(format='long', stage='preview', durationSeconds=60.0,
                                                              pixels=1920 * 1080)),
                         ['stage preview was not exercised'])

    def test_engine_identity_mismatch_is_refused(self) -> None:
        """A profile applies only to the exact engine it was qualified on."""
        usable = self.validate(fixture_profile(SHORT_SLOTS))
        other = workload(engine='f' * 64)
        self.assertEqual(profiles.mismatches(usable, other),
                         [f"engine ffffffffffff is not the qualified engine {TEST_ENGINE['identity'][:12]}"])
        mode, _outside = qualification.mode_for(qualification.Committed((usable,), {'path': '/TEST'}), other)
        self.assertEqual((mode.name, mode.rejected), ('exclusive', 'no qualification profile covers this workload'))
        self.assertIn('is not the qualified engine', mode.record['unmatched'][0])
        self.assertEqual(profiles.mismatches(usable, workload(engine=None))[0][:15], 'engine None is ')

    def test_cold_and_warm_evidence_are_distinguished(self) -> None:
        """Warm-only or partial-only evidence never authorizes an admission that cannot see the cache."""
        for state in ('warm', 'partial'):
            usable = self.validate(fixture_profile(SHORT_SLOTS, [fixture_job(i, cacheState=state) for i in range(3)]))
            with self.subTest(state=state):
                self.assertEqual(usable['workload']['formats']['short']['cacheStates'], [state])
                self.assertIn('only warm or partial source caches were exercised; admission cannot establish a '
                              'warm cache', profiles.mismatches(usable, workload()))
        mixed = [fixture_job(0), fixture_job(1, cacheState='warm'), fixture_job(2)]
        usable = self.validate(fixture_profile(SHORT_SLOTS, mixed))
        self.assertEqual((usable['workload']['formats']['short']['cacheStates'],
                          profiles.mismatches(usable, workload())), (['cold', 'warm'], []))


class ProfileAdmissionTests(unittest.TestCase):
    """The real pool selects, records and enforces profiles per request."""

    def setUp(self) -> None:
        """Private namespace, one TEST Short and one TEST Long project."""
        self.root = isolate_pool(self)
        self.short = plan_project(self, 'short', 45.0)
        self.long = plan_project(self, 'long', 600.0)

    def request(self, project: Path, stage: str = 'pipeline', lane: str = 'heavy') -> pool.PoolRequest:
        """A request whose receipt names its owner stage, withdrawn at cleanup."""
        request = pool.PoolRequest(lane, str(project), root=str(project), receipt=str(project / f'{stage}.render.json'))
        self.addCleanup(request.withdraw)
        return request

    def acquire(self, request: pool.PoolRequest) -> object:
        """Admit through the public entry point and always close."""
        lease = work.NativeWorkLease.acquire(request.lane, request.project, request=request)
        self.addCleanup(lease.close)
        return lease

    def test_long_under_a_short_profile_waits_for_an_idle_pool(self) -> None:
        """No profile covers the Long: it keeps a ticket, holds later Shorts back and runs alone once idle."""
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS)])
        short = self.acquire(self.request(self.short))
        admission = short.admission
        self.assertEqual((admission['mode'], short.reservation_bytes), ('qualified', 6 * GIB))
        self.assertEqual((admission['modeRecord']['profile'], admission['modeRecord']['workload']['stage']),
                         ('TEST-short-heavy-only-h3a1', 'pipeline'))
        long_request = self.request(self.long)
        with self.assertRaisesRegex(NativeWorkQueued, 'already active: an uncovered workload waits for an idle pool'):
            self.acquire(long_request)
        self.assertIsNotNone(long_request.ticket)  # it keeps its place in the queue
        later = self.request(plan_project(self, 'short', 45.0))  # another Short: not the live Short's nested work
        with self.assertRaisesRegex(NativeWorkQueued, r'queued behind 1 earlier request\(s\)'):
            self.acquire(later)
        short.complete()
        long = self.acquire(long_request)
        self.assertEqual((long.admission['mode'], long.reservation_bytes), ('exclusive', 16 * GIB))
        self.assertIn('format long was not exercised', long.admission['modeRecord']['unmatched'][0])
        with self.assertRaisesRegex(NativeWorkQueued, 'waiting for member') as caught:
            self.acquire(later)
        self.assertIs(caught.exception.capacity_only, True)
        long.close()  # unverified cleanup: the exclusive member keeps its exclusivity while quarantined
        with self.assertRaisesRegex(NativeWorkQuarantined, 'outside qualification profile .* unverified cleanup'):
            self.acquire(self.request(self.short))

    def test_live_member_outside_the_selected_profile_is_a_mix_wait(self) -> None:
        """A Short under a Short-only profile waits while a Long admitted under a Long-only profile runs."""
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS), long_profile()])
        long = self.acquire(self.request(self.long))
        self.assertEqual(long.admission['modeRecord']['profile'], 'TEST-long-heavy-only-h2a1')
        short = self.request(self.short)
        with self.assertRaisesRegex(NativeWorkQueued, 'waiting for member.* outside qualification profile '
                                                      'TEST-short-heavy-only'):
            self.acquire(short)
        long.complete()
        self.acquire(short).complete()

    def test_a_queued_ticket_learns_its_engine_when_a_profile_appears(self) -> None:
        """A ticket queued under schema 1 is rewritten with its engine once schema 2 needs it."""
        directory = qualify_fixture_host(self, SHORT_SLOTS)
        holders = [self.acquire(self.request(self.short)) for _ in range(3)]
        waiting = self.request(self.short)
        with self.assertRaisesRegex(NativeWorkQueued, 'all 3 heavy slot'):
            self.acquire(waiting)
        ticket = self.root / 'pool-v1' / waiting.ticket.name
        self.assertIsNone(json.loads(ticket.read_text())['workload']['engine'])
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS)], directory=directory)
        with self.assertRaises(NativeWorkQueued):  # schema-1 holders are outside the schema-2 profile: a wait
            self.acquire(waiting)
        self.assertEqual(json.loads(ticket.read_text())['workload']['engine'], TEST_ENGINE['identity'])
        for lease in holders:
            lease.complete()

    def test_unexercised_stage_or_class_is_admitted_exclusive(self) -> None:
        """A heavy-only Short profile does not admit audio owners or unexercised stages beside it."""
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS)])
        for stage, lane in (('audio-stage', 'audio'), ('preview-picture-4', 'heavy')):
            lease = self.acquire(self.request(self.short, stage, lane))
            with self.subTest(stage=stage):
                self.assertEqual(lease.admission['mode'], 'exclusive')
                self.assertEqual(lease.admission['modeRecord']['workload']['stage'], workloads.stage_label(stage))
            lease.complete()

    def test_engine_binding_uses_the_real_engine_identity(self) -> None:
        """Unpatched hashing: a profile bound to this checkout's engine applies; another engine's does not."""
        real = workloads.engine_record()
        qualify_fixture_profiles(self, [dict(fixture_profile(SHORT_SLOTS), id='TEST-real', engine=real),
                                        dict(long_profile(), engine=dict(TEST_ENGINE))], engine=None)
        lease = self.acquire(self.request(self.short))
        self.assertEqual((lease.admission['mode'], lease.admission['modeRecord']['engine']),
                         ('qualified', real['identity']))
        self.assertEqual(lease.admission['modeRecord']['workload']['engine'], real['identity'])
        lease.complete()
        lease = self.acquire(self.request(self.long))
        self.assertEqual(lease.admission['mode'], 'exclusive')
        unmatched = ' '.join(lease.admission['modeRecord']['unmatched'])
        self.assertIn(f"engine {real['identity'][:12]} is not the qualified engine {TEST_ENGINE['identity'][:12]}",
                      unmatched)
        lease.complete()


if __name__ == '__main__':
    unittest.main()
