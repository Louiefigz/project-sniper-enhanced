"""Static exact-inventory gate for all production audio mix consumers."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.program_mix_registry import (  # noqa: E402
    PROJECT_ROOT,
    _dependency_errors,
    discover_mix_occurrences,
    load_program_mix_registry,
    validate_program_mix_registry,
)


class ProgramMixRegistryTests(unittest.TestCase):
    def test_registry_is_exact_bijection_with_source_discovery(self) -> None:
        result = validate_program_mix_registry()
        self.assertEqual(result, {
            "status": "pass",
            "consumerCount": 22,
            "occurrenceCount": 19,
            "programConsumers": 18,
            "assetOnlyExemptions": 4,
            "boundaryCount": 3,
            "dependencyCount": 18,
        })

    def test_float_concats_are_program_consumers_without_exemptions(self) -> None:
        """Both FFmpeg joins and Python byte joins retain explicit authority."""
        registry = load_program_mix_registry()
        owned = {row["id"]: row for row in registry["consumers"]}
        dependencies = {row["consumerId"] for row in registry["dependencies"]}
        ids = {f"{prefix}-{suffix}" for prefix in (
            "ordinary-source-float", "private-cut-preview-float")
            for suffix in ("jcut-concat", "byte-concat")}
        ids.add("native-retained-dialogue-float-concat")
        self.assertTrue(ids <= dependencies)
        for ident in ids:
            self.assertEqual(owned[ident]["consumerKind"], "derived-program-mix")
            self.assertIsNone(owned[ident]["exemption"])
            self.assertTrue(owned[ident]["authorityPaths"])
            self.assertTrue(owned[ident]["testPaths"])

    def test_unknown_mix_literal_fails_the_gate(self) -> None:
        registry = load_program_mix_registry()
        root = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(dir="/private/tmp")))
        source = root / "scripts" / "producer" / "audio"
        source.mkdir(parents=True)
        (source / "unknown.py").write_text(
            'GRAPH = "[0:a][1:a]amix=inputs=2[out]"\\n',
            encoding="utf-8")
        occurrences = discover_mix_occurrences(root, registry)
        self.assertEqual(len(occurrences), 1)
        self.assertNotIn(
            occurrences[0]["path"],
            {row["path"] for row in registry["consumers"]})

    def test_removing_any_registered_authority_token_fails(self) -> None:
        registry = load_program_mix_registry()
        dependency = registry["dependencies"][0]
        root = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(dir="/private/tmp")))
        for row in dependency["enforcementTokens"]:
            path = root / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(row["token"] + "\n")
        self.assertEqual(_dependency_errors(root, dependency), [])
        removed = dependency["enforcementTokens"][0]
        (root / removed["path"]).write_text(
            "authority dependency removed", encoding="utf-8")
        self.assertRegex(
            "; ".join(_dependency_errors(root, dependency)),
            "enforcement token was removed")

    def test_all_authority_and_test_paths_are_repository_files(self) -> None:
        registry = load_program_mix_registry()
        for row in [
            *registry["consumers"], *registry["boundaries"]]:
            for field in ("authorityPaths", "testPaths"):
                for relative in row[field]:
                    self.assertTrue(
                        (PROJECT_ROOT / relative).is_file(),
                        f"{row['id']} missing {relative}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
