"""Adversarial closed-document tests for owner provenance and held-out media."""
from __future__ import annotations

import tempfile
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

from _native_service_rate_fixture import HOST, fixture, saved
from native_work_service_pins import document, identity
from native_work_service_schema import validate_document


class ServiceProvenanceTests(unittest.TestCase):
    """No host namespace or actual qualification is used by synthetic evidence."""

    def setUp(self) -> None:
        """Prepare independently varied TEST pictures sharing the same audio bytes."""
        temp = tempfile.TemporaryDirectory(prefix='TEST-service-provenance-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.record, self.bindings = fixture(self.root)
        self.row = self.record['serviceRates'][0]
        self.manifest = document(self.row['measurement']['manifest'])

    def adopt_changed_manifest(self) -> None:
        """Rebind outer assertions so only actual inner owner evidence can reject."""
        self.row['measurement']['manifest'] = saved(self.root, 'changed-manifest.json', self.manifest)
        validation = document(self.row['adoption']['validation'])
        validation['measurement'] = self.row['measurement']['manifest']
        validation['rateIdentity'] = identity({key: value for key, value in self.row.items()
                                                if key not in ('adoption', 'writtenAt')})
        self.row['adoption']['validation'] = saved(self.root, 'changed-validation.json', validation)

    def validate(self) -> list[dict]:
        """Use the full reader, replacing only actual host/runtime identities."""
        with patch('native_work_service_schema.current_bindings', return_value=self.bindings):
            return validate_document(self.record, HOST)

    def test_current_metadata_cannot_repackage_old_owners(self) -> None:
        """Fresh manifest/adoption cannot relabel completed owners from another engine."""
        engine = {'identity': 'f' * 64, 'files': 1}
        self.row['engine'] = self.manifest['engine'] = engine
        self.bindings = (engine, self.bindings[1])
        self.adopt_changed_manifest()
        with self.assertRaisesRegex(ValueError, 'Owner request provenance'):
            self.validate()

    def changed_owner(self, operation: str, mutation: str) -> None:
        """Retain a repinned TEST result whose original owner launch is invalid."""
        run = self.manifest['runs'][0]
        measured = document(run['measurement'])
        reference = measured['preparation' if operation == 'prepare' else 'inspection']
        file = Path(reference['owner'])
        owner = document({'path': str(file), 'bytes': file.stat().st_size, 'sha256': reference['ownerSha256']})
        if mutation == 'args':
            owner['args'][2] = str(self.root / 'other-worker.py')
        else:
            owner['additionalFilePinsBefore'].pop(owner['args'][2])
            owner['additionalFilePinsAfter'].pop(owner['args'][2])
        proof = saved(file.parent, file.name, owner)
        reference['ownerSha256'] = proof['sha256']
        run['measurement'] = saved(self.root, 'changed-run.json', measured)
        self.adopt_changed_manifest()

    def test_both_owner_commands_and_code_pins_are_required(self) -> None:
        """Changing either preparation or measurement execution refuses before adoption."""
        for operation, mutation in product(('prepare', 'measure'), ('args', 'pins')):
            self.record, self.bindings = fixture(self.root)
            self.row = self.record['serviceRates'][0]
            self.manifest = document(self.row['measurement']['manifest'])
            self.changed_owner(operation, mutation)
            with self.subTest(operation=operation, mutation=mutation), self.assertRaises(ValueError):
                self.validate()

    def test_same_picture_bytes_renamed_are_not_held_out(self) -> None:
        """Another owner, receipt and filename do not establish varied picture inputs."""
        self.record, self.bindings = fixture(self.root, b'TEST training')
        with self.assertRaisesRegex(ValueError, 'repeats training media'):
            self.validate()

    def test_manifest_cannot_relabel_actual_comparison_source(self) -> None:
        """The original owner-selected serial comparison cannot move to another row."""
        self.manifest['runs'][2]['referenceId'] = 'training'
        self.adopt_changed_manifest()
        with self.assertRaisesRegex(ValueError, 'comparison identity differs'):
            self.validate()

    def test_varied_pictures_may_share_audio(self) -> None:
        """Shared master content does not erase independently varied picture evidence."""
        self.assertEqual(self.validate(), self.record['serviceRates'])
