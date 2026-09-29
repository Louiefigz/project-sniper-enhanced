"""Qualification evidence from TEST receipts: owner overlap, summed memory, cache state, refusals.

Only receipt-shaped TEST files and rows are used; nothing runs a pool, an export or ffmpeg.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from native_render_resources import GIB
from _native_pool_fixture import TEST_ENGINE


class EvidenceTests(unittest.TestCase):
    """Owner overlap, summed memory, cache state and profile refusals from TEST receipts."""

    def folder(self) -> Path:
        """A private TEST attempt folder."""
        temporary = tempfile.TemporaryDirectory(prefix='pool-evidence-')
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def test_simultaneous_owners_of_one_job_are_summed(self) -> None:
        """Two owners of one job in the same bucket add up; the old per-job maximum undercounted."""
        from studio.pool_qualification_evidence import resource_summary
        rows = [{'job': 'A', 'owner': 'A/pipeline.resources.jsonl', 'at': 0.5, 'owned': 2 * GIB, 'pressure': 1,
                 'free': 50.0, 'disk': 100},
                {'job': 'A', 'owner': 'A/audio-stage/audio-stage.resources.jsonl', 'at': 1.0, 'owned': GIB,
                 'pressure': 1, 'free': 49.0, 'disk': 90},
                {'job': 'A', 'owner': 'A/pipeline.resources.jsonl', 'at': 2.0, 'owned': GIB, 'pressure': 2,
                 'free': 51.0, 'disk': 95},
                {'job': 'B', 'owner': 'B/pipeline.resources.jsonl', 'at': 3.0, 'owned': 3 * GIB, 'pressure': 1,
                 'free': 48.0, 'disk': 80}]
        summary = resource_summary(rows)
        self.assertEqual((summary['aggregatePeakOwnedBytes'], summary['maximumKernelPressureLevel'],
                          summary['minimumFreePercent'], summary['minimumDiskFreeBytes']), (6 * GIB, 2, 48.0, 80))

    def test_overlap_counts_owners_by_class(self) -> None:
        """Heavy and audio owners are counted per owner; back-to-back owners never overlap."""
        from studio.pool_qualification_evidence import overlap
        def owner(lane: str, start: float, end: float, label: str = 'pipeline') -> dict:
            """One TEST owner receipt summary with its admission and completion instants."""
            return {'class': lane, 'label': label, 'admittedAtEpoch': start, 'completedAtEpoch': end}
        jobs = [{'id': 'A', 'owners': [owner('audio', 1, 5, 'audio-stage'), owner('heavy', 5, 10)]},
                {'id': 'B', 'owners': [owner('heavy', 2, 12), owner('heavy', 3, 4)]}]
        self.assertEqual(overlap(jobs), {'jobsWithHeavyPeak': 2, 'heavyOwnersPeak': 2, 'audioOwnersPeak': 1,
                                         'audioWithHeavyPeak': 1, 'audioStageWithHeavyPeak': 1})
        self.assertEqual(overlap([{'id': 'A', 'owners': [owner('audio', 1, 2), owner('heavy', 2, 3)]}])
                         ['audioWithHeavyPeak'], 0)
        packaging = [{'id': 'A', 'owners': [owner('heavy', 1, 9), owner('audio', 2, 3, 'preview-package')]},
                     {'id': 'B', 'owners': [owner('audio', 4, 5, 'audio-stage'), owner('heavy', 9, 12)]}]
        self.assertEqual({key: overlap(packaging)[key] for key in ('audioWithHeavyPeak', 'audioStageWithHeavyPeak')},
                         {'audioWithHeavyPeak': 1, 'audioStageWithHeavyPeak': 1})
        apart = [{'id': 'A', 'owners': [owner('heavy', 1, 3), owner('audio', 2, 3, 'preview-package')]},
                 {'id': 'B', 'owners': [owner('audio', 3, 4, 'audio-stage')]}]
        self.assertEqual(overlap(apart)['audioStageWithHeavyPeak'], 0)

    def test_cache_state_comes_from_source_cache_receipts(self) -> None:
        """Decoded entries mean cold, store hits warm, both partial; no receipt records nothing."""
        from studio.pool_qualification_evidence import cache_state
        cases = {'cold': {'native-capture': [('k1', 'published-by-this-job'), ('k2', 'published-by-another-live-job')],
                          'render-source-view': [('k1', 'store-hit'), ('k2', 'store-hit')]},
                 'warm': {'native-capture': [('k1', 'store-hit')], 'render-source-view': [('k1', 'store-hit')]},
                 'partial': {'native-capture': [('k1', 'published-by-this-job'), ('k2', 'store-hit')]},
                 None: {}}
        for expected, receipts in cases.items():
            attempt = self.folder()
            for folder, entries in receipts.items():
                (attempt / folder).mkdir()
                (attempt / folder / 'source-cache.json').write_text(json.dumps(
                    {'entries': [{'contentKey': key, 'outcome': outcome} for key, outcome in entries]}))
            with self.subTest(expected=expected):
                self.assertEqual(cache_state(attempt)['cacheState'], expected)

    def test_jobs_without_plan_facts_or_cache_state_refuse_a_profile(self) -> None:
        """A profile needs each job's format, duration, picture size and cache state."""
        from studio.pool_qualification_profile import profile_refusals
        job = {'id': 'A', 'status': 'native-short-checked-for-review', 'format': 'short', 'planFormat': 'unbound',
               'durationSeconds': None, 'pixels': None, 'cacheState': None}
        summary = {'jobs': [job], 'configuration': {'heavySlots': 2, 'audioSlots': 1}, 'overlap': {}}
        reasons = profile_refusals(summary, 'heavy-only', (dict(TEST_ENGINE), dict(TEST_ENGINE)))
        self.assertEqual(len(reasons), 3)
        self.assertIn("from a unbound project is not a Short or Long final export", reasons[0])


if __name__ == '__main__':
    unittest.main()
