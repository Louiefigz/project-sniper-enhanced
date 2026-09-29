"""Retained Long frames consume admitted disk without a second assembly reservation."""
from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from native_work_pool_policy import DISK_RESERVATION_BYTES
from studio.native_budget_owner import long_owner_disk, short_disk_projection
from studio.native_long_contract import disk_projection
from studio.native_long_export import prepare_sections
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest


class RetainedLongDiskTests(unittest.TestCase):
    """Use actual request preparation and owner configuration, without starting media work."""

    def setUp(self) -> None:
        """Construct a full program exceeding the default lane reservation."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cli = self.root / 'cli.js'
        self.cli.write_text('// TEST ONLY')
        sandbox = Path(__file__).resolve().parents[1] / 'studio/native_localhost_only.sb'
        self.settings = NativeRunConfig(self.root, self.root, self.cli, [], {}, {
            'output': str(self.root / 'result.json'), 'sdkSha256': digest(self.cli),
            'sandboxSha256': digest(sandbox)})
        canvas = {'width': 1920, 'height': 1080, 'frameRate': '25/1', 'totalFrames': 15000}
        self.plan = {'canvas': canvas, 'scenes': [{'startFrame': 0, 'endFrame': 15000}]}

    def request(self, scope: list[int] | None = None) -> dict:
        """Run the actual initial Long section preparation for a full or scoped invocation."""
        args = argparse.Namespace(project=self.root, sections=True, section_plan=None,
                                  repair_from=None, resume_from=None)
        request = {'pins': {}, 'project': str(self.root), 'output': str(self.root / 'attempt')}
        if scope is not None:
            request['sectionScope'] = {'frameRange': scope}
        prepare_sections(args, request, self.plan)
        return request

    def test_full_and_scoped_preparation_count_only_selected_windows(self) -> None:
        """A private section reserves its frames, while full integration projects all frames."""
        pixels = 1920 * 1080 * 4
        full, scoped = self.request(), self.request([250, 750])
        self.assertEqual(full['diskProjection']['retainedFrameBytes'], 15000 * pixels)
        self.assertEqual(scoped['diskProjection']['retainedFrameBytes'], 500 * pixels)
        self.assertEqual(scoped['diskProjection']['outputBytes'],
                         disk_projection(self.plan)['outputBytes'] + 500 * pixels)

    def test_assembly_reserves_only_future_encoded_output(self) -> None:
        """Existing JPEGs count in observed used disk, not a new allocation at assembly."""
        request = self.request()
        base = disk_projection(self.plan)
        expected = max(DISK_RESERVATION_BYTES['heavy'], base['outputBytes'] + base['miscBytes'])
        for label in ('picture', 'pipeline'):
            owner = long_owner_disk(self.settings, request, label)
            self.assertTrue(owner.disk_expansion)
            self.assertEqual(owner.disk_reservation_bytes, expected)

    def test_window_owner_reserves_capture_and_encoding_headroom(self) -> None:
        """Each parallel window obtains its own bounded future allocation before capture."""
        request = self.request()
        owner = long_owner_disk(self.settings, request, 'segment-picture-1')
        expected = max(DISK_RESERVATION_BYTES['heavy'], 250 * 1920 * 1080 * 4 + 1024 ** 3)
        self.assertEqual(owner.disk_reservation_bytes, expected)

    def test_capture_reservation_stays_separate(self) -> None:
        """Reference-capture owners do not reserve the whole retained final inventory."""
        request = self.request()
        owner = long_owner_disk(self.settings, request, 'capture')
        expected = max(DISK_RESERVATION_BYTES['heavy'],
                       request['diskProjection']['sampleBytes'] + 1024 ** 3)
        self.assertEqual(owner.disk_reservation_bytes, expected)

    def test_invalid_retention_cannot_reduce_assembly_reservation(self) -> None:
        """Booleans, negative values and inflated subtractions fail before resource admission."""
        request = self.request()
        for value in (True, -1, request['diskProjection']['outputBytes'],
                      request['diskProjection']['outputBytes'] + 1):
            request['diskProjection']['retainedFrameBytes'] = value
            with self.assertRaisesRegex(ValueError, 'invalid retained Long disk projection'):
                long_owner_disk(self.settings, request, 'picture')

    def test_invalid_projection_count_refuses(self) -> None:
        """A projection cannot silently admit an unbounded or nonintegral frame inventory."""
        for value in (True, -1, 15001, 1.5):
            with self.assertRaisesRegex(ValueError, 'invalid retained Long frame count'):
                disk_projection(self.plan, value)

    def test_legacy_and_short_projection_contracts_remain_distinct(self) -> None:
        """The Long retention field neither changes Short geometry nor suppresses legacy output."""
        request = {'diskProjection': disk_projection(self.plan)}
        expected = request['diskProjection']['outputBytes'] + 1024 ** 3
        self.assertEqual(long_owner_disk(self.settings, request, 'pipeline').disk_reservation_bytes,
                         max(DISK_RESERVATION_BYTES['heavy'], expected))
        short = short_disk_projection({'totalFrames': 100})
        self.assertEqual(short['outputBytes'], 100 * 1080 * 1920 * 4)
        self.assertNotIn('retainedFrameBytes', short)

    def test_future_jpeg_metadata_is_accounted_before_any_capture_exists(self) -> None:
        """Assembly owner maps contain every completed JPEG even when each window is small."""
        from studio.native_segments.frame_metadata import metadata_lower_bounds
        full = metadata_lower_bounds(self.request(), {}, ({}, {}))
        scoped = metadata_lower_bounds(self.request([250, 750]), {}, ({}, {}))
        self.assertGreater(full['futureOwner'], full['request'])
        self.assertGreater(full['futureOwner'], scoped['futureOwner'] * 10)

    def test_known_oversize_receipt_refuses_before_owner_creation(self) -> None:
        """The request can fit while duplicated owner maps are already structurally too large."""
        from studio.native_segments.frame_metadata import require_retained_metadata_capacity
        request = self.request([0, 250])
        request['pins'] = {f'/TEST/{index:06d}/' + 'x' * 400: 'a' * 64 for index in range(20000)}
        with self.assertRaisesRegex(ValueError, 'necessarily exceeds existing JSON bound before media'):
            require_retained_metadata_capacity(request)

    def test_completed_capture_paths_replace_projection_without_double_counting(self) -> None:
        """Later owners size the actual successful try once, preserving room for missing windows."""
        from studio.native_segments.frame_metadata import future_frame_pins, metadata_lower_bounds
        request = self.request([0, 250])
        projected = future_frame_pins(request, {})
        actual = {file.replace('-try-7/', '-try-0/').replace('-retry-1.render', '.render'): sha
                  for file, sha in projected.items()}
        self.assertEqual(set(future_frame_pins(request, actual)), set(actual))
        sizes = metadata_lower_bounds(request, actual, ({}, {}))
        uncompleted = metadata_lower_bounds(request, {}, ({}, {}))
        self.assertLessEqual(sizes['futureOwner'], uncompleted['futureOwner'])
