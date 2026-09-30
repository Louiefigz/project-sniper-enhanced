"""Cross-module contracts hold across the reconciled engine (P0 Step 7.2; static, no process or media).

Report A §4: every mixed-version defect lived where import and arity checks cannot see: a module attribute a caller
uses that its module lacks (M1), and a record field a reader needs that no writer writes (M2, M3, M8). These tests
run the static audit (``_contract_audit``, ``_contract_calls``, ``_contract_records``) over scripts/producer and
the curated table ``fixtures/record_contracts.json``. Self-tests on temporary packages prove each rule can fail.
Limits are in ``_contract_audit``'s docstring: curated contracts, no TS/JS writers, no data flow through helpers.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _contract_audit as audit
import _contract_calls as calls
import _contract_records as records

# Frozen base-engine copies run with their own directory first on sys.path (tests/fixtures/base_pool_driver.py),
# so the tree-wide index would resolve their imports to the live modules; they are not audited.
FROZEN = ('tests/fixtures/base_pool_4a15560/', 'tests/fixtures/base_pool_driver.py')
# The two C-6 rows (test_transitions_ban.py:70 and speech_cleanup.py:84) were fixed at M-040 (FOLLOWUP-C6).
KNOWN_ATTRIBUTES = {
    'tests/test_native_short_regions.py:117 studio.native_preview_sections.planned_preview_workload is not defined':
        ('P4', "pending('P4') workload hook with no production caller (NOT-PORTED; M-121a)"),
}
KNOWN_CALLS: dict[str, tuple[str, str]] = {}


def write(root: Path, name: str, text: str) -> None:
    """One TEST module file under a temporary producer root."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class ContractAuditTests(unittest.TestCase):
    """The reconciled engine has no unknown missing attribute, call or record key."""

    def test_no_module_attribute_is_missing(self) -> None:
        """Every alias.attr, getattr literal and local from-import resolves, apart from the KNOWN rows."""
        found = [row.key() for row in audit.missing_attributes(audit.PRODUCER, FROZEN)]
        self.assertEqual(sorted(set(found) - set(KNOWN_ATTRIBUTES)), [])
        self.assertEqual(sorted(set(KNOWN_ATTRIBUTES) - set(found)), [], 'a KNOWN row is fixed: remove it')

    def test_no_call_uses_a_parameter_its_callee_lacks(self) -> None:
        """No call to a local def passes too many positionals or an unknown keyword, apart from KNOWN."""
        found = [row.key() for row in calls.call_arity(audit.PRODUCER, FROZEN)]
        self.assertEqual(sorted(set(found) - set(KNOWN_CALLS)), [])
        self.assertEqual(sorted(set(KNOWN_CALLS) - set(found)), [], 'a KNOWN row is fixed: remove it')

    def test_every_record_contract_is_written(self) -> None:
        """Each curated contract's required keys are written by its writers."""
        self.assertEqual(records.contract_problems(records.load_contracts()), [])

    def test_no_esm_named_import_is_missing(self) -> None:
        """Every named import of a relative .mjs/.js module under scripts/ is exported by it."""
        self.assertEqual([row.key() for row in records.esm_missing(audit.PRODUCER.parent)], [])


class AuditSelfTests(unittest.TestCase):
    """Temporary TEST packages: each rule reports what it exists to catch, so the audit cannot silently pass."""

    def setUp(self) -> None:
        """A private producer-shaped root."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        write(self.root, 'studio/__init__.py', '')

    def test_audit_finds_a_missing_module_function(self) -> None:
        """(M1) The caller uses state.settle_launch; the state module lacks it: one finding."""
        write(self.root, 'studio/state.py', 'def served_cli():\n    return None\n')
        write(self.root, 'studio/preview.py', 'from studio import state\n\n\ndef open_view():\n'
                                              '    state.served_cli()\n    return state.settle_launch()\n')
        found = [row.key() for row in audit.missing_attributes(self.root)]
        self.assertEqual(found, ['studio/preview.py:6 studio.state.settle_launch is not defined'])

    def test_a_local_name_shadows_a_module_alias(self) -> None:
        """A parameter named like an alias is not the module: no finding for its attributes."""
        write(self.root, 'studio/state.py', 'X = 1\n')
        write(self.root, 'studio/user.py', 'from studio import state\n\n\ndef read(state):\n    return state.anything\n')
        self.assertEqual(audit.missing_attributes(self.root), [])

    def test_audit_finds_a_call_with_an_unknown_keyword(self) -> None:
        """A keyword the callee lacks is reported; *args/**kwargs callees are not."""
        write(self.root, 'studio/work.py', 'def run(a, b=1):\n    return a\n\n\ndef loose(**options):\n    return options\n')
        write(self.root, 'studio/caller.py', 'from studio import work\n\n\ndef go():\n'
                                             '    work.loose(retakes=1)\n    return work.run(1, retakes=2)\n')
        self.assertEqual([row.key() for row in calls.call_arity(self.root)],
                         ["studio/caller.py:6 studio.work.run: unknown keyword ['retakes']"])

    def test_audit_finds_a_missing_record_key(self) -> None:
        """(M2) native_run.py without supervisorPid: the audio-worker contract fails."""
        row = next(row for row in records.load_contracts() if row['name'] == 'owner receipt -> audio worker')
        for name in row['writers']:
            text = (audit.PRODUCER / name).read_text()
            write(self.root, name, text.replace("'supervisorPid': os.getpid(),", '') if name.endswith('native_run.py')
                  else text)
        problems = records.contract_problems([row], self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("['supervisorPid']", problems[0])

    def test_audit_finds_an_event_without_approval(self) -> None:
        """(M3) The pre-M3 authorize_output event, without its approval, fails the output-authorized contract."""
        row = next(row for row in records.load_contracts() if row.get('event') == 'output-authorized')
        text = (audit.PRODUCER / 'studio/production/api.py').read_text()
        before = text.replace("\n                 'approval': approvals[0]['identity'] if approvals else None,"
                              '  # read_approval checks the chain', '')   # M-052 moved the line (duplicationCheck)
        self.assertNotEqual(before, text, 'the M3 approval line moved: update this self-test')
        write(self.root, 'studio/production/api.py', before)
        self.assertIn("['approval']", records.contract_problems([row], self.root)[0])

    def test_dynamic_module_is_reported_not_passed(self) -> None:
        """A module that writes its own globals() cannot be proven to define anything: reported."""
        write(self.root, 'studio/magic.py', "globals()['settle'] = lambda: None\n")
        write(self.root, 'studio/user.py', 'from studio import magic\n\n\ndef go():\n    return magic.settle()\n')
        found = [row.key() for row in audit.missing_attributes(self.root)]
        self.assertEqual(found, ['studio/user.py:5 studio.magic is dynamic (globals/setattr/__getattr__)'])

    def test_contract_table_is_well_formed(self) -> None:
        """Every row names writers that exist, one writer kind, required keys and readers."""
        table = json.loads((audit.PRODUCER / 'tests/fixtures/record_contracts.json').read_text())
        for row in table['contracts']:
            with self.subTest(row=row['name']):
                self.assertEqual(len({'owners', 'event', 'literal'} & set(row)), 1)
                self.assertTrue(row['required'] and row['readers'])
                self.assertTrue(all((audit.PRODUCER / name).is_file() for name in row['writers']))


if __name__ == '__main__':
    unittest.main()
