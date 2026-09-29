"""The standards checkers report each rule they claim, keep line-shift-stable baselines, and exempt only named catalogs."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import standards_check as checker

TESTS = Path(__file__).resolve().parent
NODE = shutil.which('node')


def body(lines: int) -> str:
    """A function body of exactly ``lines`` statement lines."""
    return ''.join('    x = 1\n' for _ in range(lines))


class PythonRuleTests(unittest.TestCase):
    """Each Python rule is detected on a seeded file."""

    def seeded(self, text: str, name: str = 'seeded.py') -> Path:
        """Write one temporary source file."""
        folder = Path(tempfile.mkdtemp(prefix='standards-'))
        self.addCleanup(shutil.rmtree, folder)
        path = folder / name
        path.write_text(text)
        return path

    def rules(self, path: Path, catalogs: set[str] = frozenset()) -> set[str]:
        """The rule names the checker reports for one file."""
        return {row.rule for row in checker.check(path, set(catalogs))}

    def test_each_rule_is_detected(self) -> None:
        """Length, parameters, nesting, hints and docstrings are each reported."""
        long = self.seeded('def f() -> None:\n    """Doc."""\n' + body(49))
        many = self.seeded('def f(a: int, b: int, c: int, d: int, e: int) -> None:\n    """Doc."""\n')
        deep = self.seeded('def f(a: int) -> None:\n    """Doc."""\n    if a:\n        for b in []:\n'
                           '            while b:\n                pass\n')
        bare = self.seeded('def f(a):\n    return a\n\n\nclass C:\n    pass\n')
        self.assertIn('function-lines', self.rules(long))
        self.assertIn('parameters', self.rules(many))
        self.assertIn('nesting', self.rules(deep))
        self.assertEqual(self.rules(bare), {'return-hint', 'parameter-hints', 'docstring'})

    def test_a_clean_file_and_an_elif_chain_pass(self) -> None:
        """An elif chain stays at its if's level; self is not a parameter; exactly 50 lines is allowed."""
        clean = self.seeded('class C:\n    """Doc."""\n\n    def m(self, a: int, b: int, c: int, d: int) -> int:\n'
                            '        """Doc."""\n        if a:\n            for x in []:\n                pass\n'
                            '        elif b:\n            pass\n        elif c:\n            pass\n        return d\n')
        fifty = self.seeded('def f() -> None:\n    """Doc."""\n' + body(48))
        self.assertEqual(self.rules(clean), set())
        self.assertEqual(self.rules(fifty), set())

    def test_data_catalog_exempts_only_the_file_length(self) -> None:
        """A named catalog may exceed 300 lines; its functions are still checked."""
        path = self.seeded('ROWS = [\n' + ''.join('    1,\n' for _ in range(310)) + ']\n\n\ndef f(a):\n    return a\n')
        self.assertIn('file-lines', self.rules(path))
        self.assertNotIn('file-lines', self.rules(path, {str(path)}))
        self.assertIn('return-hint', self.rules(path, {str(path)}))

    def test_baseline_keys_survive_a_line_shift_but_not_a_worse_value(self) -> None:
        """A recorded violation passes until it gets worse."""
        first = checker.check(self.seeded('def f(a: int, b: int, c: int, d: int, e: int) -> None:\n    """D."""\n'), set())
        baseline = {row.key(): row.value for row in first}
        shifted = [checker.Violation(row.path, row.line + 7, row.rule, row.name, row.value) for row in first]
        worse = [checker.Violation(row.path, row.line, row.rule, row.name, row.value + 1) for row in first]
        self.assertEqual(checker.compare(shifted, baseline)[0], [])
        self.assertEqual(len(checker.compare(worse, baseline)[0]), 1)


@unittest.skipIf(NODE is None, 'node is not on PATH')
class TypeScriptRuleTests(unittest.TestCase):
    """The TypeScript checker reports its rules on a seeded file."""

    def test_each_rule_is_detected(self) -> None:
        """Length, parameters, nesting and missing JSDoc on an export are reported; a clean export passes."""
        folder = Path(tempfile.mkdtemp(prefix='ts-standards-'))
        self.addCleanup(shutil.rmtree, folder)
        seeded = folder / 'seeded.ts'
        lines = ''.join('  x += 1;\n' for _ in range(52))
        seeded.write_text('export function longOne(): void {\n  let x = 0;\n' + lines + '}\n'
                          '/** Documented. */\nexport function many(a: 1, b: 2, c: 3, d: 4, e: 5): void {}\n'
                          '/** Documented. */\nexport function deep(a: boolean): void {\n  if (a) {\n    for (;;) {\n'
                          '      while (a) { break; }\n    }\n  }\n}\n'
                          '/** Documented. */\nexport function chain(a: number): number {\n  if (a) { return 1; }\n'
                          '  else if (a > 1) { return 2; }\n  return 0;\n}\n')
        result = subprocess.run([NODE, str(TESTS / 'ts_standards_check.cjs'), str(seeded)], capture_output=True,
                                text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        reported = {line.split()[2] + ':' + line.split()[3] for line in result.stdout.splitlines() if line.startswith('VIOLATION')}
        self.assertEqual(reported, {'function-lines:longOne', 'jsdoc:longOne', 'parameters:many', 'nesting:deep'})
        self.assertIn('ts standards: 4 new, 0 recorded in the baseline, 1 file(s)', result.stdout)

    def test_a_checker_that_cannot_run_exits_2_not_1(self) -> None:
        """An unreadable input is a crash (2), never a violation report (1) (CS1-REVIEW m5)."""
        missing = Path(tempfile.mkdtemp(prefix='ts-standards-')) / 'absent.ts'
        self.addCleanup(shutil.rmtree, missing.parent)
        result = subprocess.run([NODE, str(TESTS / 'ts_standards_check.cjs'), str(missing)], capture_output=True,
                                text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('ts standards checker could not run', result.stderr)
        self.assertNotIn('ts standards:', result.stdout)

    def test_write_and_use_a_baseline(self) -> None:
        """A written baseline suppresses the same violations."""
        folder = Path(tempfile.mkdtemp(prefix='ts-standards-'))
        self.addCleanup(shutil.rmtree, folder)
        seeded, baseline = folder / 'seeded.ts', folder / 'baseline.json'
        seeded.write_text('export function many(a: 1, b: 2, c: 3, d: 4, e: 5): void {}\n')
        subprocess.run([NODE, str(TESTS / 'ts_standards_check.cjs'), '--write-baseline', str(baseline), str(seeded)],
                       check=True, capture_output=True, timeout=60)
        self.assertEqual(len(json.loads(baseline.read_text())), 2)
        result = subprocess.run([NODE, str(TESTS / 'ts_standards_check.cjs'), '--baseline', str(baseline), str(seeded)],
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main()
