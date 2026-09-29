"""Tests for bounded Python/TypeScript persistence-call discovery."""
from __future__ import annotations

import unittest

from current_system_persistence_audit import (
    audit_persistence_calls,
    persistence_sites,
)


class CurrentSystemPersistenceAuditTests(unittest.TestCase):
    """Prove writer extraction and artifact binding remain fail-closed."""

    def test_path_read_string_replace_does_not_hide_real_path_replace(self) -> None:
        """Content replacement after an exact Path read is not filesystem mutation."""
        from current_system_python_persistence import python_persistence_rows
        source = '\n'.join([
            'from pathlib import Path',
            'source = Path("source.txt")',
            'source.read_text().replace("old", "new")',
            'source.read_bytes().replace(b"old", b"new")',
            'source.replace("new.txt")',
            'Path("other.txt").replace("moved.txt")',
            'source.resolve().replace("resolved.txt")',
        ])
        rows = python_persistence_rows('example.py', source)
        self.assertEqual(sorted(line for _name, line in rows), [5, 6, 7])

    def test_python_ast_distinguishes_read_and_write_open(self) -> None:
        sites = persistence_sites({
            "src/example.py": (
                "from pathlib import Path\n"
                'with open("input.json") as source:\n'
                "    source.read()\n"
                'with open("output.json", "wb") as target:\n'
                "    target.write(b'x')\n"
                'Path("sidecar.json").write_text("{}")\n'
            ),
        })
        self.assertEqual(
            [(row.callee, row.line) for row in sites],
            [("open", 4), ("write_text", 6)],
        )

    def test_python_ast_distinguishes_os_open_flags(self) -> None:
        sites = persistence_sites({
            "src/example.py": (
                "import os\n"
                'os.open("input.json", os.O_RDONLY | os.O_NOFOLLOW)\n'
                'os.open("output.json", os.O_WRONLY | os.O_CREAT)\n'
            ),
        })
        self.assertEqual(
            [(row.callee, row.line) for row in sites],
            [("os.open", 3)],
        )

    def test_typescript_ignores_comments_and_strings(self) -> None:
        sites = persistence_sites({
            "src/example.ts": (
                'import { writeFileSync } from "node:fs";\n'
                '// writeFileSync("fake", "x");\n'
                'const text = "renameSync(fake)";\n'
                'writeFileSync(target, bytes);\n'
                "atomicWriteJsonSync(receipt, value);\n"
            ),
        })
        self.assertEqual(
            [row.callee for row in sites],
            ["writeFileSync", "atomicWriteJsonSync"],
        )

    def test_artifact_writer_owns_every_site_in_its_file(self) -> None:
        result = audit_persistence_calls(
            {"src/example.ts": (
                'import { writeFileSync } from "node:fs";\n'
                "writeFileSync(target, bytes);\n"
            )},
            [{"artifactId": "example", "writers": ["src/example.ts"]}],
        )
        self.assertEqual(result["artifactBoundSites"], 1)
        self.assertEqual(result["unboundSites"], 0)

    def test_unowned_writer_is_reported_with_exact_location(self) -> None:
        result = audit_persistence_calls(
            {"src/example.py": 'open("output", "w").write("x")\n'},
            [],
        )
        self.assertEqual(result["unboundSites"], 1)
        self.assertEqual(result["unboundFiles"], ["src/example.py"])
        self.assertEqual(
            result["unboundExamples"], ["src/example.py:1:open"])


if __name__ == "__main__":
    unittest.main()
