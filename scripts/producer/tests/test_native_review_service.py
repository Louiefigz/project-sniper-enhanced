"""Rate helper arithmetic over cold authored geometry; no measurement or adoption claim."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from unittest.mock import patch

import test_native_long_chunk_admission as fixtures
from native_work_service_pins import identity
from native_work_service_rates import RateCatalog
from studio.native_segments.review_service import planned_service
from studio.native_segments.review_service_estimate import estimate_service
from studio.native_segments.review_service_plan import SITES, VERSION, remaining_selection


def conditions(canvas: dict) -> dict:
    """Explicit TEST already-admitted facts; production must supply its actual owner conditions."""
    return {'format': 'long', 'stage': 'review-package',
            'canvas': {key: canvas[key] for key in ('width', 'height', 'frameRate')},
            'encoderContractSha256': 'c' * 64,
            'audio': {'sampleRate': 48000, 'channels': 2, 'sampleFormat': 'pcm_f32le'},
            'filesystem': {'type': 'TEST-local', 'volumeIdentity': 'TEST-volume'},
            'cacheRegime': 'unknown', 'execution': {'ownedConcurrency': 1}, 'proofPlanVersion': VERSION}


def catalog(contract: dict) -> RateCatalog:
    """Synthetic pure-selector input; sidecar evidence/adoption validation is tested separately."""
    cells = []
    for site, (unit, _entrypoint) in SITES.items():
        cells.append({'id': site, 'unit': unit, 'contract': {**contract, 'proofPlanVersion': f'{VERSION}:{site}'},
            'bounds': {'minFrames': 1, 'maxFrames': 30000, 'maxWindows': 200,
                       'maxPictureBytes': 10 ** 8, 'maxPeakBitrate': 10 ** 9,
                       'maxMasterBytes': 10 ** 9, 'maxReferenceBytes': 10 ** 9,
                       'maxPinnedInputBytes': 10 ** 10, 'maxProofFiles': 10000},
            'runIds': ['TEST-training'], 'heldOutRunIds': ['TEST-heldout'],
            'marginFactor': 1.25, 'ceilingSeconds': 2.0})
    return RateCatalog(rows=({'id': 'TEST-rate', 'cells': cells},),
                       source={'path': '/TEST/not-adopted.json', 'sha256': 'a' * 64, 'bytes': 1})


class ReviewServiceTests(unittest.TestCase):
    """Use the actual cold Long contract fixture, never a made-up future media manifest."""

    def setUp(self) -> None:
        """Create real authored geometry and isolate only the supplied rate evidence."""
        self.case = fixtures.ChunkAdmissionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.conditions = conditions(self.case.canvas)
        self.catalog = catalog(self.conditions)

    def plan(self, rates: RateCatalog | None = None) -> dict:
        """Freeze normal coordinator demand without creating output media or authority."""
        return planned_service(self.case.project, self.case.context, rates or self.catalog, self.conditions)

    def test_real_geometry_has_all_transition_scopes_and_no_future_hashes(self) -> None:
        """Actual expanded edges, owner ranges and clock determine service demand."""
        evidence = self.plan()
        self.assertEqual(evidence['windows'], 60)
        self.assertEqual(len(evidence['scopes']), 19)
        self.assertEqual({row['kind'] for row in evidence['scopes']},
                         {'chunk', 'neighboring-edge', 'global-neighboring-edge'})
        self.assertTrue(all(row['windows'] == len(row['windowRanges']) for row in evidence['scopes']))
        self.assertNotIn('sha256', str(evidence['knownInputs']['inventory']))
        self.assertNotIn('sourceHash', evidence)
        self.assertEqual(evidence['readPlan']['additionalDemand'],
                         ['external-inspection', 'callback-replay', 'recovery', 'retry'])

    def test_entrypoint_call_bounds_cover_each_window_completion_and_integration(self) -> None:
        """Two 30-window assignments each have their own passes plus the full 60-window invocation."""
        evidence = self.plan()
        calls = evidence['readPlan']['calls']
        first = evidence['scopes'][0]['id']
        global_id = next(row['id'] for row in evidence['scopes'] if len(row['sectionIds']) == 2)
        counts = {(row['site'], row['scopeId']): row['calls'] for row in calls}
        self.assertEqual(counts['ready-discovery', first], 92)
        self.assertEqual(counts['ready-discovery', global_id], 61)
        self.assertEqual(counts['review-progress', global_id], 0)
        self.assertEqual(counts['family-outcome', first], 4)
        self.assertEqual(counts['assembly', first], 2)
        self.assertEqual(counts['package-create', first], 1)

    def test_explicit_remaining_selection_prices_calls_without_scanning_completion(self) -> None:
        """The caller states every remaining counter; the estimator performs no filesystem discovery."""
        evidence = self.plan()
        remaining = remaining_selection(evidence)
        with patch('pathlib.Path.exists', side_effect=AssertionError('mutable completion inference')):
            result = estimate_service(evidence, self.catalog, remaining)
        self.assertEqual(result['status'], 'measured')
        self.assertEqual(result['seconds'], 2 * sum(remaining['calls'].values()))
        remaining['calls'] = {key: 0 for key in remaining['calls']}
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['seconds'], 0)

    def test_missing_conditions_catalog_or_any_read_site_retains_fallback(self) -> None:
        """A fast remux measurement cannot silently cover coordinator, reviewer or final proof reads."""
        no_conditions = planned_service(self.case.project, self.case.context, self.catalog)
        self.assertTrue(all(row['selection'] is None for row in no_conditions['envelopes']))
        for name in SITES:
            with self.subTest(site=name):
                rates = copy.deepcopy(self.catalog)
                rates.rows[0]['cells'][:] = [cell for cell in rates.rows[0]['cells'] if cell['id'] != name]
                evidence = self.plan(rates)
                self.assertEqual(estimate_service(evidence, rates, remaining_selection(evidence))['status'], 'fallback')
        evidence = self.plan()
        empty = RateCatalog(rejected='TEST deleted sidecar')
        self.assertEqual(estimate_service(evidence, empty, remaining_selection(evidence))['status'], 'fallback')

    def test_changed_rate_never_rewrites_frozen_envelope(self) -> None:
        """A new faster cell is not adoption for a previously frozen family decision."""
        evidence = self.plan()
        before = copy.deepcopy(evidence)
        rates = copy.deepcopy(self.catalog)
        rates.rows[0]['cells'][0]['ceilingSeconds'] = 1
        result = estimate_service(evidence, rates, remaining_selection(evidence))
        self.assertEqual(result['status'], 'fallback')
        self.assertEqual(evidence, before)

    def test_extrapolation_warm_cache_and_partial_remaining_inventory_are_refused(self) -> None:
        """A duration match alone cannot waive unknown-cache, geometry or recurrence requirements."""
        rates = copy.deepcopy(self.catalog)
        rates.rows[0]['cells'][0]['bounds']['maxFrames'] = 10
        evidence = self.plan(rates)
        self.assertEqual(estimate_service(evidence, rates, remaining_selection(evidence))['status'], 'fallback')
        rates = copy.deepcopy(self.catalog)
        rates.rows[0]['cells'][0]['contract']['cacheRegime'] = 'observed-warm'
        with self.assertRaisesRegex(ValueError, 'Warm service'):
            self.plan(rates)
        evidence = self.plan()
        calls = remaining_selection(evidence)['calls']
        calls.pop(next(iter(calls)))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            remaining_selection(evidence, calls)

    def observed(self, evidence: dict, whole: bool = False) -> dict:
        """Explicit TEST descriptor supplied by an authority; no mutable work inference."""
        scope = evidence['scopes'][0]
        facts = {'frames': evidence['canvas']['totalFrames'] if whole else scope['frames'],
                 'windows': evidence['windows'] if whole else scope['windows'],
                 'pictureBytes': 100, 'peakBitrate': 1000, 'masterBytes': 100,
                 'referenceBytes': 100, 'pinnedInputBytes': 1000, 'proofFiles': 10}
        return {'status': 'eligible', 'reasons': [], 'facts': facts, 'mediaValidated': True}

    def test_read_envelopes_never_borrow_package_eligibility(self) -> None:
        """A 100-byte master fits the package but exceeds every one-byte read ceiling."""
        rates = copy.deepcopy(self.catalog)
        for cell in rates.rows[0]['cells']:
            if cell['unit'] == 'cold-proof-read':
                cell['bounds']['maxMasterBytes'] = 1
        evidence = self.plan(rates)
        remaining = remaining_selection(evidence)
        remaining['actual'][evidence['scopes'][0]['id']] = self.observed(evidence)
        self.assertEqual(estimate_service(evidence, rates, remaining)['status'], 'fallback')
        remaining['actualReads'] = {row['key']: self.observed(evidence, True)
                                    for row in evidence['readPlan']['calls'] if row['unit'] == 'cold-proof-read'}
        self.assertEqual(estimate_service(evidence, rates, remaining)['status'], 'fallback')

    def test_read_units_require_whole_inventory_and_every_remaining_site(self) -> None:
        """Per-scope bytes cannot cover a whole-program read; no overlapping scope sum is inferred."""
        evidence = self.plan()
        remaining = remaining_selection(evidence)
        remaining['actual'][evidence['scopes'][0]['id']] = self.observed(evidence)
        remaining['actualReads'] = {row['key']: self.observed(evidence, True)
                                    for row in evidence['readPlan']['calls'] if row['unit'] == 'cold-proof-read'}
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['status'], 'measured')
        key = next(iter(remaining['actualReads']))
        remaining['actualReads'][key] = self.observed(evidence)
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['status'], 'fallback')
        remaining['actualReads'].pop(key)
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['status'], 'fallback')
        remaining['calls'][key] = 0
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['status'], 'measured')
        remaining['actualReads'][key] = self.observed(evidence, True)
        remaining['actualReads'][key]['facts']['pictureBytes'] = 10 ** 12
        remaining['calls'][key] = 1
        self.assertEqual(estimate_service(evidence, self.catalog, remaining)['status'], 'fallback')

    def test_additional_inspection_is_unpriced_demand_not_media_invalidation(self) -> None:
        """Extra work requests fallback; no file or editorial state is changed by estimation."""
        evidence = self.plan()
        remaining = remaining_selection(evidence)
        remaining['additionalDemand'] = ['callback-replay']
        result = estimate_service(evidence, self.catalog, remaining)
        self.assertEqual(result['status'], 'fallback')
        self.assertIn('additional', result['reason'])
        self.assertGreater(result['seconds'], 0)
        evidence['windows'] += 1
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            estimate_service(evidence, self.catalog, remaining)


if __name__ == '__main__':
    unittest.main()
