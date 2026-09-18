"""Tests for the fail-closed current-system call-site inventory audit."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from current_system_inventory_check import validate_inventory


def _artifact() -> dict:
    return {
        "artifactId": "example-authority",
        "pathPattern": "<root>/authority.json",
        "owner": "src/authority.py",
        "authority": "canonical",
        "readers": ["src/authority.py"],
        "writers": ["src/authority.py"],
        "promotionPoint": "test",
        "fingerprintInputs": [],
        "durability": "test",
        "disposition": "reuse",
        "parityFixture": "test",
        "removalCondition": "test",
        "authorityPathTokens": ["authority.json", ".hidden-authority.json"],
        "callSiteDispositions": {
            "src/authority.py": "reader-writer",
        },
    }


def _inventory() -> dict:
    return {
        "schemaVersion": 1,
        "asOf": "2026-07-29",
        "completeness": "partial",
        "phaseExit": "blocked",
        "baseline": {
            "status": "required-unmeasured",
            "requiredFixtures": ["short", "long"],
            "evidencePaths": [],
        },
        "callSiteAudit": {
            "roots": ["src"],
            "extensions": [".py"],
            "excludedPathSegments": ["tests"],
        },
        "authorityDiscovery": {
            "literalPrefixes": [".hidden-"],
            "artifactBindings": {
                ".hidden-authority.json": "example-authority",
            },
            "backlog": {
                ".hidden-backlog.json": "not yet inventoried",
            },
            "pathBoundaryEvidence": "path-evidence.json",
            "persistenceDispositionEvidence": "persistence-evidence.json",
        },
        "artifacts": [_artifact()],
    }


def _path_evidence() -> dict:
    concerns = [
        "caller-supplied-output-root",
        "dynamically-constructed-filename",
        "external-store",
        "non-prefixed-authority",
    ]
    records = []
    for index, concern in enumerate(concerns):
        records.append({
            "evidenceId": f"evidence-{index}",
            "concern": concern,
            "disposition": "artifact-bound",
            "artifactIds": ["example-authority"],
            "finding": "retained test evidence",
            "sites": [{
                "path": "src/authority.py",
                "tokens": ["authority.json"],
            }],
        })
    return {
        "schemaVersion": 1,
        "asOf": "2026-07-29",
        "concerns": concerns,
        "records": records,
        "knownLimitations": ["manual evidence is bounded"],
    }


def _persistence_evidence(
    site_ids: list[str] | None = None,
    unknown_paths: list[str] | None = None,
) -> dict:
    ids = site_ids or []
    paths = unknown_paths or []
    dispositions = {
        "tests-fixtures": "excluded-non-production",
        "docs-build-tooling": "excluded-non-production",
        "temp-cache": "excluded-ephemeral",
        "governed-production-authority": "blocking-artifact-binding",
        "delivery-output": "blocking-artifact-binding",
        "unknown": "blocking-unknown",
    }
    return {
        "schemaVersion": 1,
        "asOf": "2026-07-29",
        "siteCount": len(ids),
        "fileCount": len(paths),
        "siteSetDigest": hashlib.sha256(
            ("\n".join(sorted(ids)) + "\n").encode()).hexdigest(),
        "categories": {
            name: {
                "disposition": disposition,
                "rationale": "retained test classification",
                "paths": paths if name == "unknown" else [],
            }
            for name, disposition in dispositions.items()
        },
        "sideEffectBoundaries": {
            "siteCount": 0,
            "fileCount": 0,
            "siteSetDigest": hashlib.sha256(b"\n").hexdigest(),
            "categories": {
                name: {
                    "disposition": disposition,
                    "rationale": "retained empty boundary classification",
                    "paths": [],
                }
                for name, disposition in dispositions.items()
            },
        },
        "knownLimitations": ["bounded test evidence"],
    }


class CurrentSystemInventoryCheckTests(unittest.TestCase):
    """Exercise exact-match and drift failures."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "authority.py").write_text(
            'PATH = "authority.json"\n'
            'HIDDEN = ".hidden-authority.json"\n'
            'BACKLOG = ".hidden-backlog.json"\n',
            encoding="utf-8")
        (self.root / "path-evidence.json").write_text(
            json.dumps(_path_evidence()), encoding="utf-8")
        (self.root / "persistence-evidence.json").write_text(
            json.dumps(_persistence_evidence()), encoding="utf-8")
        self.inventory_path = self.root / "inventory.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, inventory: dict) -> None:
        self.inventory_path.write_text(
            json.dumps(inventory), encoding="utf-8")

    def test_accepts_exact_disposed_call_site_set(self) -> None:
        self._write(_inventory())
        result = validate_inventory(self.root, self.inventory_path)
        self.assertEqual(result["disposedCallSites"], 1)
        self.assertEqual(result["baselineEvidence"], 0)
        self.assertEqual(result["discoveredAuthorityLiterals"], 2)
        self.assertEqual(result["discoveryBacklog"], 1)
        self.assertEqual(result["pathBoundaryEvidence"]["records"], 4)

    def test_rejects_new_undisposed_call_site(self) -> None:
        (self.root / "src" / "rogue.py").write_text(
            'PATH = "authority.json"\n', encoding="utf-8")
        self._write(_inventory())
        with self.assertRaisesRegex(RuntimeError, "undisposed=.*rogue.py"):
            validate_inventory(self.root, self.inventory_path)

    def test_rejects_absent_declared_call_site(self) -> None:
        inventory = _inventory()
        inventory["artifacts"][0]["callSiteDispositions"] = {
            "src/missing.py": "reader",
            "src/authority.py": "reader-writer",
        }
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "absent=.*missing.py"):
            validate_inventory(self.root, self.inventory_path)

    def test_rejects_absent_authority_token(self) -> None:
        inventory = _inventory()
        inventory["artifacts"][0]["authorityPathTokens"] = ["missing.json"]
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "authority token is absent"):
            validate_inventory(self.root, self.inventory_path)

    def test_rejects_new_undisposed_hidden_authority_literal(self) -> None:
        (self.root / "src" / "rogue.py").write_text(
            'PATH = ".hidden-rogue.json"\n', encoding="utf-8")
        self._write(_inventory())
        with self.assertRaisesRegex(
                RuntimeError, "literal discovery drift; undisposed="):
            validate_inventory(self.root, self.inventory_path)

    def test_rejects_discovery_binding_without_artifact_token(self) -> None:
        inventory = _inventory()
        inventory["authorityDiscovery"]["artifactBindings"][
            ".hidden-authority.json"] = "example-authority"
        inventory["artifacts"][0]["authorityPathTokens"] = ["authority.json"]
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "bypasses artifact tokens"):
            validate_inventory(self.root, self.inventory_path)

    def test_rejects_stale_manual_path_evidence(self) -> None:
        evidence = _path_evidence()
        evidence["records"][0]["sites"][0]["tokens"] = ["missing-call-site"]
        (self.root / "path-evidence.json").write_text(
            json.dumps(evidence), encoding="utf-8")
        self._write(_inventory())
        with self.assertRaisesRegex(RuntimeError, "evidence drift"):
            validate_inventory(self.root, self.inventory_path)

    def test_complete_inventory_rejects_unbound_persistence_call(self) -> None:
        (self.root / "src" / "rogue.py").write_text(
            'open("unbound.json", "w").write("{}")\n', encoding="utf-8")
        inventory = _inventory()
        inventory["completeness"] = "complete"
        inventory["authorityDiscovery"]["backlog"] = {}
        (self.root / "src" / "authority.py").write_text(
            'PATH = "authority.json"\n'
            'HIDDEN = ".hidden-authority.json"\n',
            encoding="utf-8")
        (self.root / "persistence-evidence.json").write_text(
            json.dumps(_persistence_evidence(
                ["src/rogue.py:1:open"], ["src/rogue.py"])),
            encoding="utf-8",
        )
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "blocking persistence calls"):
            validate_inventory(self.root, self.inventory_path)

    def test_complete_inventory_rejects_discovery_backlog(self) -> None:
        inventory = _inventory()
        inventory["completeness"] = "complete"
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "discovery backlog"):
            validate_inventory(self.root, self.inventory_path)

    def test_measured_baseline_requires_existing_closed_traces(self) -> None:
        inventory = _inventory()
        inventory["baseline"] = {
            "status": "measured",
            "requiredFixtures": ["short", "long"],
            "evidencePaths": ["short.json", "long.json"],
        }
        self._write(inventory)
        with self.assertRaisesRegex(RuntimeError, "evidence is unavailable"):
            validate_inventory(self.root, self.inventory_path)
        (self.root / "short.json").write_text("{}", encoding="utf-8")
        (self.root / "long.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not one closed trace"):
            validate_inventory(self.root, self.inventory_path)

    def test_repository_measured_baselines_are_closed(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        inventory = (
            repo / "docs/producer/command-driven-editing/contracts/"
            "current-system-inventory-v1.json"
        )
        inventory.stat()  # absent retained evidence fails as FileNotFoundError, not a wrapped error
        result = validate_inventory(repo, inventory)
        self.assertEqual(result["baselineEvidence"], 2)
        self.assertEqual(result["discoveryBacklog"], 0)
        self.assertEqual(
            result["persistenceDispositions"]["blockingSites"], 0)
        self.assertEqual(
            result["persistenceDispositions"]["unknownSites"], 0)


if __name__ == "__main__":
    unittest.main()
