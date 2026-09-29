"""Operational misses preserve actual StageEvidence around explicitly fictional media."""
from __future__ import annotations

import copy
import json
import unittest
from fractions import Fraction
from math import ceil
from pathlib import Path
from unittest.mock import patch

import test_production_chunk_dispatch as fixtures
from cut_preview_io import bound_json
from native_work_service_pins import identity
from studio.native_runtime import digest
from studio.native_segments.owners import current_window
from studio.native_segments.review_service import planned_service
from studio.native_segments.review_service_actual import actual_service, dimensions
from studio.native_segments.review_service_estimate import estimate_service
from studio.native_segments.review_service_plan import remaining_selection
from test_native_review_service import catalog, conditions


class ActualReviewServiceTests(unittest.TestCase):
    """Only media generation is synthetic; cold source/seal validation remains real."""

    def setUp(self) -> None:
        """Use the public admitted chunk fixture without changing its production authority."""
        self.case = fixtures.ChunkDispatchTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.host
        self.conditions = conditions(self.host.request['revision']['canvas'])
        self.evidence = planned_service(self.host.fixture.project, self.host.context,
                                        catalog(self.conditions), self.conditions)
        self.scope_id = self.evidence['scopes'][0]['id']

    def test_missing_stream_facts_are_operational_misses_without_losing_seals(self) -> None:
        """A valid older seal lacking rate facts is retained and independently remains current."""
        self.host.seal(0)
        root = self.host.fixture.root
        seal = root / 'segment-picture-0-stage.json'
        before = seal.read_bytes()
        result = actual_service(self.host.request, self.scope_id, self.evidence, self.conditions)
        self.assertEqual(result['status'], 'miss')
        self.assertTrue(result['mediaValidated'])
        self.assertIn('encoder:changed-or-unobserved', result['reasons'])
        self.assertIn('audio:changed-or-unobserved', result['reasons'])
        self.assertEqual(seal.read_bytes(), before)
        current_window(self.host.request, 'segment-picture-0')

    def test_size_miss_precedes_source_hashing_and_preserves_media(self) -> None:
        """An exercised byte ceiling is eligibility, never permission to discard completed work."""
        self.host.seal(0)
        evidence = copy.deepcopy(self.evidence)
        for row in evidence['envelopes']:
            if row['selection']:
                row['selection']['bounds']['maxPictureBytes'] = 0
        evidence['identity'] = identity({key: value for key, value in evidence.items() if key != 'identity'})
        value = current_window(self.host.request, 'segment-picture-0')
        file = Path(value['piece']['path'])
        before = file.read_bytes()
        with patch('studio.native_segments.review_media.source_state', side_effect=AssertionError('hash before stat')):
            result = actual_service(self.host.request, self.scope_id, evidence, self.conditions)
        self.assertEqual(result['status'], 'miss')
        self.assertFalse(result['mediaValidated'])
        self.assertIn('pictureBytes:outside-envelope', result['reasons'])
        self.assertEqual(file.read_bytes(), before)
        current_window(self.host.request, 'segment-picture-0')

    def test_current_observed_contract_is_eligible_but_cannot_override_byte_limits(self) -> None:
        """Explicit TEST stream metadata is sealed before checking operational eligibility."""
        original = self.host.fixture.write_phase

        def add_facts(label: str, root: Path) -> None:
            """Add fictional owned facts before the real fixture StageEvidence is sealed."""
            original(label, root)
            file = root / f'{label}.json'
            value = bound_json(file)
            value['encoder'] = {'contractSha256': self.conditions['encoderContractSha256']}
            value['piece']['stream'] = {'width': 320, 'height': 180, 'r_frame_rate': '1/1'}
            file.write_text(json.dumps(value))

        prepared_file = self.host.fixture.root / 'prepared-audio.json'
        prepared = bound_json(prepared_file)
        master_file = Path(prepared['masterReceipt'])
        master = bound_json(master_file)
        master['masterClock'] = {'sampleRate': 48000, 'channels': 2, 'sampleFormat': 'flt', 'codec': 'pcm_f32le'}
        master_file.write_text(json.dumps(master))
        prepared['masterReceiptSha256'] = digest(master_file)
        prepared_file.write_text(json.dumps(prepared))
        with patch.object(self.host.fixture, 'write_phase', side_effect=add_facts):
            self.host.seal(0)
        result = actual_service(self.host.request, self.scope_id, self.evidence, self.conditions)
        self.assertEqual(result['status'], 'eligible')
        remaining = remaining_selection(self.evidence)
        remaining['actual'][self.scope_id] = result
        rates = catalog(self.conditions)
        self.assertEqual(estimate_service(self.evidence, rates, remaining)['status'], 'fallback')
        remaining['calls'] = {key: value if row['site'] == 'package-create' else 0
                              for row in self.evidence['readPlan']['calls']
                              for key, value in [(row['key'], remaining['calls'][row['key']])]}
        self.assertEqual(estimate_service(self.evidence, rates, remaining)['status'], 'measured')
        result['facts']['pictureBytes'] = 10 ** 12
        self.assertEqual(estimate_service(self.evidence, rates, remaining)['status'], 'fallback')
        current_window(self.host.request, 'segment-picture-0')

    def test_corrupt_seal_remains_an_evidence_error_not_a_rate_miss(self) -> None:
        """Rate fallback cannot turn corrupted current picture into reusable media."""
        self.host.seal(0)
        value = current_window(self.host.request, 'segment-picture-0')
        Path(value['piece']['path']).write_bytes(b'TEST corrupt')
        with self.assertRaises((ValueError, RuntimeError)):
            actual_service(self.host.request, self.scope_id, self.evidence, self.conditions)

    def test_coarse_peak_predictor_uses_exact_fraction_and_actual_largest_file(self) -> None:
        """No bitrate probe or rounded FPS is needed for the safe one-frame file-size bound."""
        self.host.seal(0)
        value = current_window(self.host.request, 'segment-picture-0')
        root = self.host.fixture.root
        prepared = bound_json(root / 'prepared-audio.json')
        master = bound_json(Path(prepared['masterReceipt']))
        file = Path(value['piece']['path'])
        facts = dimensions({'frameRange': [0, 60], 'frameRate': '30000/1001'}, [value],
                           {'master': master, 'prepared': prepared}, [file])
        self.assertEqual(facts['peakBitrate'], ceil(file.stat().st_size * 8 * Fraction(30000, 1001)))
        self.assertEqual(facts['masterBytes'], Path(master['output']).stat().st_size)
        self.assertEqual(facts['referenceBytes'], Path(prepared['reference']).stat().st_size)


if __name__ == '__main__':
    unittest.main()
