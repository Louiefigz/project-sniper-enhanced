"""Committed qualification records: schema 1 serves what schema 2 does not bound; forecasts.

TEST records for a TEST host (and TEST engine identity) in temporary folders; the pool
namespace is private and the canonical host record is never read.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import native_work_qualification as qualification
import native_work_workload as workloads
from _native_pool_fixture import (
    TEST_HOST, fixture_profile, isolate_pool, profile_record, qualify_fixture_host, qualify_fixture_profiles,
)
from test_native_work_profiles import SHORT_SLOTS, workload
from test_native_work_profiles import long_profile
from studio.native_budget_forecast import heavy_lane_capacity


class CommittedRecordTests(unittest.TestCase):
    """The schema-1 record serves what schema 2 does not bound; the forecast uses real durations."""

    def setUp(self) -> None:
        """TEST namespace; the record folder is patched to a TEST folder."""
        isolate_pool(self)
        heavy_lane_capacity.cache_clear()
        self.addCleanup(heavy_lane_capacity.cache_clear)

    def mode(self, item: dict) -> object:
        """The committed mode one workload gets on the TEST host."""
        return qualification.committed_mode(dict(TEST_HOST), item)

    def test_current_host_record_shape_keeps_serving_short_batches(self) -> None:
        """Schema 1 (3 heavy, 1 audio, Short evidence) covers Shorts, unbound and older-client owners, never Longs."""
        qualify_fixture_host(self, SHORT_SLOTS)
        record = qualification.committed(dict(TEST_HOST))
        self.assertEqual((record.source['records'][0]['schemaVersion'], record.needs_engine, record.legacy_qualified),
                         (1, False, True))
        for item in (workload(engine=None), workload(format='unbound', stage='native-review', engine=None),
                     workload(stage='audio-stage', engine=None, durationSeconds=180.0, **{'class': 'audio'}),
                     workloads.unrecorded('audio')):
            mode = self.mode(item)
            self.assertEqual((mode.name, mode.slots, mode.record['legacy']), ('qualified', SHORT_SLOTS, True))
        long = self.mode(workload(format='long', engine=None))
        self.assertEqual(long.name, 'exclusive')
        self.assertIn('format long was not exercised (short, unbound, unrecorded)', long.record['unmatched'][0])

    def test_schema_one_serves_what_schema_two_does_not_bound(self) -> None:
        """A Short profile bounds Shorts; unbound and older-client owners stay on schema 1; a bad file is named."""
        directory = qualify_fixture_host(self, SHORT_SLOTS)
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS)], directory=directory)
        record = qualification.committed(dict(TEST_HOST))
        self.assertEqual([profile['id'] for profile in record.profiles], ['TEST-short-heavy-only-h3a1', 'legacy-v1'])
        self.assertEqual(sorted(record.profiles[1]['workload']['formats']), ['unbound', 'unrecorded'])
        self.assertEqual(self.mode(workload(format='unbound', stage='native-review')).record['profile'], 'legacy-v1')
        self.assertEqual(self.mode(workload(durationSeconds=61.0)).name, 'exclusive')
        (directory / qualification.RECORD_V2_NAME).write_text(json.dumps(profile_record(
            [dict(fixture_profile(SHORT_SLOTS), workload={'classMix': 'heavy-only', 'formats': {}})])))
        record = qualification.committed(dict(TEST_HOST))
        self.assertIn(qualification.RECORD_V2_NAME, record.rejected)
        self.assertEqual([profile['id'] for profile in record.profiles], ['legacy-v1'])

    def test_forecast_uses_the_batch_durations(self) -> None:
        """--pool-slots gets the best Short capacity; each launch forecast its real duration."""
        qualify_fixture_host(self, SHORT_SLOTS)
        self.assertEqual(qualification.forecast_mode(dict(TEST_HOST)).slots, SHORT_SLOTS)
        four = {'heavy': 4, 'audio': 1}
        qualify_fixture_profiles(self, [fixture_profile(four)], directory=qualification.record_directory())
        self.assertEqual(qualification.forecast_mode(dict(TEST_HOST)).slots, four)
        self.assertEqual(qualification.forecast_mode(dict(TEST_HOST), 60.0).slots, four)
        longer = qualification.forecast_mode(dict(TEST_HOST), 61.0)
        self.assertEqual(longer.name, 'exclusive')
        self.assertIn('output seconds 61.0 exceed the exercised 60.0', longer.record['unmatched'][0])

    def test_section_labels_share_only_their_exact_stage(self) -> None:
        """Section indices and retry indices cannot broaden a picture owner's capacity class."""
        for label in ('segment-picture-0', 'segment-picture-767', 'segment-picture-2-retry-1'):
            self.assertEqual(workloads.stage_label(label), 'segment-picture')
        self.assertEqual(workloads.stage_label('segment-picture-bogus'), 'segment-picture-bogus')

    def test_real_capacity_reader_keeps_short_default_and_refuses_unbound_long(self) -> None:
        """The real three-argument call cannot borrow a Short or geometry-bound Long profile."""
        qualify_fixture_profiles(self, [fixture_profile(SHORT_SLOTS), long_profile()])
        with patch('native_work_pool_policy.host_identity', return_value=dict(TEST_HOST)):
            self.assertEqual(heavy_lane_capacity(45.0), 3)
            self.assertEqual(heavy_lane_capacity(45.0, 'short'), 3)
            self.assertEqual(heavy_lane_capacity(600.0, 'long'), 1)
            self.assertEqual(heavy_lane_capacity(None, 'long'), 1)
        mode = qualification.forecast_mode(dict(TEST_HOST), 600.0, 'long')
        self.assertEqual(mode.record['workload']['format'], 'long')
        self.assertIsNone(mode.record['workload']['stage'])
        self.assertIsNone(mode.record['workload']['pixels'])
        self.assertIn('project-bound', mode.rejected)

    def test_real_capacity_reader_never_borrows_legacy_short_capacity_for_long(self) -> None:
        """A legacy qualified host still needs actual Long geometry and stages for forecasts."""
        qualify_fixture_host(self, SHORT_SLOTS)
        with patch('native_work_pool_policy.host_identity', return_value=dict(TEST_HOST)):
            self.assertEqual(heavy_lane_capacity(45.0), 3)
            self.assertEqual(heavy_lane_capacity(600.0, 'long'), 1)
            with self.assertRaisesRegex(ValueError, 'format'):
                heavy_lane_capacity(600.0, 'unknown')


if __name__ == '__main__':
    unittest.main()
