"""External host output ownership is explicit inventory metadata, never an engine-writer exemption."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from current_system_inventory_check import _verify_declarations
from current_system_persistence_audit import audit_persistence_calls

DERIVATION = 'sectionBinding.outputRoot/task.id/claim.epoch-claim.token/{result.json,artifacts/**}'


class ExternalWriterInventoryTests(unittest.TestCase):
    """Reject unsupported host/ownership declarations and preserve raw engine-write discovery."""

    def setUp(self) -> None:
        """A private source reader stands in for the closed section result validator."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.root / 'reader.py').write_text('from pathlib import Path\nPath("unrelated.json").write_text("x")\n')
        self.artifact = {'artifactId': 'host-result', 'owner': 'reader.py', 'readers': ['reader.py'],
                         'writers': [], 'authorityPathTokens': ['result.json'], 'externalWriters': [{
                             'actor': 'codex', 'ownershipValidator': 'reader.py', 'outputDerivation': DERIVATION}]}

    def test_supported_host_can_own_output_without_fictitious_engine_writer(self) -> None:
        """A reader validator is not listed as an engine output producer."""
        _verify_declarations(self.root, self.artifact)
        self.assertEqual(self.artifact['writers'], [])
        audit = audit_persistence_calls({'reader.py': (self.root / 'reader.py').read_text()}, [self.artifact])
        self.assertEqual(audit['unboundFiles'], ['reader.py'])

    def test_unknown_host_extra_fields_or_duplicate_actor_are_rejected(self) -> None:
        """Only exact supported enrolled-host task descriptors are accepted."""
        row = self.artifact['externalWriters'][0]
        invalid = [[{**row, 'actor': 'anonymous'}], [{**row, 'approved': True}], [row, row], []]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaisesRegex(RuntimeError, 'externalWriters|writers'):
                _verify_declarations(self.root, {**self.artifact, 'externalWriters': rows})

    def test_output_derivation_and_reader_path_are_mandatory(self) -> None:
        """Caller-picked output paths and unlisted validators cannot hide authority writers."""
        for changes in ({'outputDerivation': '/arbitrary/result.json'}, {'ownershipValidator': 'absent.py'}):
            value = copy.deepcopy(self.artifact)
            value['externalWriters'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                _verify_declarations(self.root, value)
        value = copy.deepcopy(self.artifact)
        value['readers'] = []
        with self.assertRaises(RuntimeError):
            _verify_declarations(self.root, value)

    def test_validator_must_be_real_file_inside_repository(self) -> None:
        """An external descriptor cannot bypass ordinary authority evidence path rules."""
        value = copy.deepcopy(self.artifact)
        value['readers'] = ['.']
        value['externalWriters'][0]['ownershipValidator'] = '.'
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            _verify_declarations(self.root, value)

    def test_empty_engine_writers_without_external_owner_remain_invalid(self) -> None:
        """The new representation cannot silently erase an existing writer declaration."""
        value = copy.deepcopy(self.artifact)
        del value['externalWriters']
        with self.assertRaisesRegex(RuntimeError, 'writers'):
            _verify_declarations(self.root, value)

    def test_only_exact_chunk_authoring_and_claim_receipt_derivations_are_supported(self) -> None:
        """Describing host-authored chunk bytes grants no engine writer or arbitrary output path."""
        prefix = 'sectionBinding.outputRoot/task.id/claim.epoch-claim.token/'
        for path in (prefix + '{chunks/<scopeId>.json,global-joins.json}', 'request.project/LONG-CHUNKS.json'):
            value = copy.deepcopy(self.artifact)
            value['externalWriters'][0]['outputDerivation'] = path
            _verify_declarations(self.root, value)
        for path in (prefix + '**', 'request.project/**', 'request.project/../LONG-CHUNKS.json'):
            value = copy.deepcopy(self.artifact)
            value['externalWriters'][0]['outputDerivation'] = path
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'derivation'):
                _verify_declarations(self.root, value)


if __name__ == '__main__':
    unittest.main()
