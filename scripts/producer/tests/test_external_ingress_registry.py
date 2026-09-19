"""Closed-world tests for the released external-ingress inventory."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from external_ingress_registry import located, validate_external_ingress_registry


def _registry(
    *,
    owner: bool = True,
    required_token: str = "guard()",
) -> dict:
    ownership = [{
        "ruleId": "probe",
        "path": "boundary.py",
        "sourceToken": "admit(",
        "expectedOccurrences": 1,
    }] if owner else []
    return {
        "schemaVersion": 1,
        "kind": "external-ingress-registry",
        "scanRules": [{
            "ruleId": "probe",
            "roots": ["."],
            "suffixes": [".py"],
            "token": "admit(",
            "expectedOccurrenceCount": 1,
        }],
        "families": [{
            "id": "probe-family",
            "classification": "sandbox-admitted-media",
            "released": True,
            "entryPoints": ["boundary.py"],
            "authorityPaths": ["boundary.py"],
            "promotionPaths": [],
            "testPaths": ["boundary.py"],
            "ownership": ownership,
            "notes": "fixture",
        }],
        "invariants": [{
            "id": "guard-present",
            "requiredTokens": [{
                "path": "boundary.py",
                "token": required_token,
                "expectedOccurrences": 1,
            }],
            "forbiddenTokens": [],
            "testPaths": ["boundary.py"],
        }],
    }


class ExternalIngressRegistryTests(unittest.TestCase):
    def test_repository_registry_is_exact_and_complete(self) -> None:
        self.assertEqual(
            validate_external_ingress_registry(),
            {
                "status": "pass",
                "familyCount": 11,
                "releasedFamilyCount": 9,
                "occurrenceCount": 27,
                "ownerCount": 27,
                "invariantCount": 5,
            },
        )

    def _validate_fixture(
        self,
        registry: dict,
        source: str = "admit(value)\nguard()\n",
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "boundary.py").write_text(
                source, encoding="utf-8")
            with patch(
                "external_ingress_registry.load_external_ingress_registry",
                return_value=registry,
            ):
                validate_external_ingress_registry(root)

    def test_unowned_discovered_occurrence_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unowned external ingress"):
            self._validate_fixture(_registry(owner=False))

    def test_removed_authority_token_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "occurs 0, expected 1"):
            self._validate_fixture(_registry(required_token="missing_guard()"))

    def test_changed_scan_count_fails_before_registry_can_go_stale(self) -> None:
        with self.assertRaisesRegex(
                ValueError, "discovered 2 occurrences, expected 1"):
            self._validate_fixture(
                _registry(), "admit(value)\nadmit(other)\nguard()\n")

    def test_one_discovery_cannot_have_two_overlapping_owners(self) -> None:
        registry = _registry()
        registry["families"][0]["ownership"].append({
            "ruleId": "probe",
            "path": "boundary.py",
            "sourceToken": "admit(value)",
            "expectedOccurrences": 1,
        })
        with self.assertRaisesRegex(ValueError, "multiply-owned external"):
            self._validate_fixture(registry)


class PackagedInstallerPathTests(unittest.TestCase):
    """release/payload_files/<x> is <x> at the package root (the app folder) in a package, and only there."""

    def test_installer_path_is_found_where_the_package_puts_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)
            (package / "install").mkdir()
            (package / "install/sniper_doctor.py").write_text("")
            found = located(package, "release/payload_files/install/sniper_doctor.py")
            self.assertEqual(found, package / "install/sniper_doctor.py")

    def test_the_source_tree_never_looks_outside_itself(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "repo"
            (repo / "release").mkdir(parents=True)
            (Path(folder) / "install").mkdir()
            (Path(folder) / "install/sniper_doctor.py").write_text("")
            found = located(repo, "release/payload_files/install/sniper_doctor.py")
            self.assertEqual(found, repo / "release/payload_files/install/sniper_doctor.py")
            self.assertEqual(located(repo, "scripts/x.py"), repo / "scripts/x.py")


if __name__ == "__main__":
    unittest.main()
