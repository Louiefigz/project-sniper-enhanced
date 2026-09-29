"""Adversarial full rate-reader checks; every owner and counter fixture is fictional."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from pathlib import Path

import test_native_service_rate_provenance as provenance_tests
from _native_service_rate_fixture import saved
from native_work_service_pins import document
from native_work_service_cache import observation_facts, unobserved_cache
from studio.owned_inspection import read_inspection


class ServiceObservationBindingTests(unittest.TestCase):
    """Repinning outer assertions never changes the original completed owner bytes."""

    setUp = provenance_tests.ServiceProvenanceTests.setUp
    validate = provenance_tests.ServiceProvenanceTests.validate
    adopt_changed_manifest = provenance_tests.ServiceProvenanceTests.adopt_changed_manifest

    def test_rewritten_result_with_repinned_parent_and_adoption_refuses(self) -> None:
        """The original owner digest rejects changed result facts before rate coverage changes."""
        entry = self.manifest['runs'][0]
        run = document(entry['measurement'])
        reference = run['inspection']
        result = read_inspection(reference, require_owner_digest=True)
        result['dimensions']['proofFiles'] += 1
        changed = saved(Path(reference['path']).parent, 'result.json', result)
        reference['sha256'] = changed['sha256']
        run['dimensions'] = result['dimensions']
        entry['measurement'] = saved(self.root, 'tampered-run.json', run)
        self.adopt_changed_manifest()
        with self.assertRaisesRegex(ValueError, 'owner-captured result differs'):
            self.validate()

    def test_replaced_cache_counters_with_rebound_outer_artifacts_refuse(self) -> None:
        """Changing only cache wrappers cannot rewrite the owner's raw observations."""
        entry = self.manifest['runs'][0]
        run = document(entry['measurement'])
        cache = document(run['cacheEvidence'])
        facts = document(cache['observations'])
        facts.update(workingSetBytes=900000, readBytes=900000, physicalReadBytes=900000, passes=40)
        cache['observations'] = saved(self.root, 'invented-observations.json', facts)
        run['cacheEvidence'] = saved(self.root, 'invented-cache.json', cache)
        entry['measurement'] = saved(self.root, 'invented-cache-run.json', run)
        self.adopt_changed_manifest()
        with self.assertRaisesRegex(ValueError, 'owner-bound raw evidence'):
            self.validate()

    def test_legacy_preview_read_is_explicitly_not_new_calibration_evidence(self) -> None:
        """Historical absent digest is readable, while required/new calibration reads refuse."""
        run = document(self.manifest['runs'][0]['measurement'])
        reference = run['inspection']
        file = Path(reference['owner'])
        import json
        owner = json.loads(file.read_text())
        owner.pop('completedOutput')
        reference['ownerSha256'] = saved(file.parent, file.name, owner)['sha256']
        self.assertIn('contract', read_inspection(reference))
        with self.assertRaisesRegex(ValueError, 'lacks owner-captured'):
            read_inspection(reference, require_owner_digest=True)
        owner['completedOutput'] = None
        reference['ownerSha256'] = saved(file.parent, file.name, owner)['sha256']
        with self.assertRaisesRegex(ValueError, 'owner-captured result differs'):
            read_inspection(reference)
        owner['completedOutput'] = {'path': str(file), 'sha256': 'f' * 64, 'bytes': 1}
        reference['ownerSha256'] = saved(file.parent, file.name, owner)['sha256']
        with self.assertRaisesRegex(ValueError, 'owner-captured result differs'):
            read_inspection(reference)

    def test_unavailable_counters_remain_null_and_zero_kernel_delta_is_observed(self) -> None:
        """Neither missing data nor a zero kernel reading is converted into invented disk traffic."""
        run = document(self.manifest['runs'][0]['measurement'])
        result = read_inspection(run['inspection'], require_owner_digest=True)
        observation = result['cacheObservation']
        missing = unobserved_cache(run['inputPins'], observation['filesystem'], observation['host'])
        facts = observation_facts(missing, run['inputPins'], [])
        self.assertIsNone(facts['readBytes'])
        self.assertIsNone(facts['physicalReadBytes'])
        self.assertIsNone(facts['passes'])
        sample = observation['readPasses'][0]['kernelSamples'][0]
        sample['after']['diskReadBytes'] = sample['before']['diskReadBytes']
        facts = observation_facts(observation, run['inputPins'], [sample['identity']])
        self.assertEqual(facts['physicalReadBytes'], 0)
        self.assertEqual(facts['readBytes'], sum(row['bytes'] for row in run['inputPins']))

    def test_raw_counter_identity_and_pass_arithmetic_are_rechecked(self) -> None:
        """Omitted descendants, negative deltas and oversized logical reads fail closed."""
        import copy
        run = document(self.manifest['runs'][0]['measurement'])
        result = read_inspection(run['inspection'], require_owner_digest=True)
        original = result['cacheObservation']
        sample = original['readPasses'][0]['kernelSamples'][0]
        with self.assertRaisesRegex(ValueError, 'omitted or duplicated'):
            observation_facts(original, run['inputPins'], [sample['identity'], {'pid': 200}])
        bad = copy.deepcopy(original)
        bad['readPasses'][0]['kernelSamples'][0]['after']['diskReadBytes'] = 0
        with self.assertRaisesRegex(ValueError, 'kernel IO delta'):
            observation_facts(bad, run['inputPins'], [sample['identity']])
        bad = copy.deepcopy(original)
        bad['readPasses'][0]['logicalReads'][0]['returnedBytes'] = 999999
        with self.assertRaisesRegex(ValueError, 'Logical read'):
            observation_facts(bad, run['inputPins'], [sample['identity']])
