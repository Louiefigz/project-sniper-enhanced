"""Versioned, bounded full-catalog discovery foundation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphics import catalog_discovery as discovery
from graphics.catalog_discovery_sources import load_index
from graphics.catalog_discovery_validation import MAX_ROWS, MAX_TEXT
from graphics.catalog_resource_index import (
    MAX_RESOURCE_BYTES,
    build_resource_index,
    classify_source,
    load_resource_index,
)
from graphics.catalog_semantic_search import SemanticSearchRequest, semantic_search_catalog
from graphics.catalog_snapshot_admission import (
    MAX_METADATA_BYTES,
    AdmissionRequest,
    inspect_candidate,
)
from graphics.catalog_snapshot_registry import MAX_REGISTRY_BYTES, resolve_snapshot


class LiveCatalogFoundationTests(unittest.TestCase):
    """Use the production snapshot without executing catalog source."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = discovery.load_catalog()

    def search(self, *intents: str, limit: int = 5) -> dict:
        """Run the public bounded semantic search."""
        filters = discovery.SearchFilters(limit=limit)
        return semantic_search_catalog(
            self.catalog, SemanticSearchRequest(tuple(intents), filters))

    def test_tail_candidate_can_win_and_results_are_bounded(self) -> None:
        """A strong row near the index tail is not hidden by load or result bounds."""
        names = [row["id"] for row in self.catalog.records]
        self.assertGreater(names.index("testimonial-proof-card"), len(names) * 0.75)
        result = self.search("testimonial proof", limit=1)
        self.assertEqual([row["id"] for row in result["results"]],
                         ["testimonial-proof-card"])
        self.assertTrue(result["limited"])
        self.assertEqual(result["returned"], 1)

    def test_semantic_expansion_is_deterministic_and_metadata_only(self) -> None:
        """Synonyms expose useful candidates without source or preview payload bytes."""
        first = self.search("credible customer evidence", "prove the claimed result")
        second = self.search("credible customer evidence", "prove the claimed result")
        self.assertEqual(first, second)
        refs = [row["ref"] for row in first["results"]]
        self.assertTrue(any("testimonial" in ref or "chart-story" in ref for ref in refs))
        encoded = json.dumps(first, sort_keys=True)
        for forbidden in ('"sourceText"', '"previewBytes"', '"html"', "data:video"):
            self.assertNotIn(forbidden, encoded)
        self.assertLess(len(encoded), 250_000)

    def test_selection_and_execution_evidence_stay_separate(self) -> None:
        """References remain candidates, never silently executable components."""
        ascii_row = discovery.lookup_item(self.catalog, "ascii-render-pass")["matches"][0]
        self.assertTrue(ascii_row["resourceEvidence"]["canvas"])
        self.assertTrue(ascii_row["resourceEvidence"]["guardedProbeRequired"])
        self.assertEqual(ascii_row["eligibility"]["executionStatus"],
                         "native-adaptation-required")
        measured = discovery.lookup_item(self.catalog, "count-up")["matches"][0]
        self.assertEqual(measured["eligibility"]["executionStatus"],
                         "measured-compatibility-candidate")
        self.assertFalse(measured["eligibility"]["executionApproved"])
        missing = discovery.lookup_item(self.catalog, "lt-neon-border")["matches"][0]
        self.assertEqual(missing["eligibility"]["executionStatus"],
                         "blocked-missing-source")

    def test_resource_sidecar_covers_the_pinned_snapshot(self) -> None:
        """Every indexed row receives digest-bound static resource evidence."""
        provenance = self.catalog.provenance
        self.assertEqual(provenance["resourceEvidence"]["rows"], 372)
        self.assertEqual(provenance["snapshotId"],
                         "registry-cli-0.7.33-2026-08-28")
        self.assertEqual(provenance["issues"], [])


class ResourceEvidenceTests(unittest.TestCase):
    def test_static_heavy_signals_require_probe_without_claiming_measurement(self) -> None:
        """Static flags inform admission but never become a capability verdict."""
        with tempfile.TemporaryDirectory(prefix="catalog-resource-", dir="/private/tmp") as tmp:
            root = Path(tmp)
            (root / "asset.bin").write_bytes(b"1234")
            source = root / "heavy.html"
            source.write_text("""<canvas id='stage'></canvas><video></video><video></video>
                <script src='asset.bin'></script><script>
                const texture = new THREE.VideoTexture(document.querySelector('#stage'));
                </script>""")
            result = classify_source(str(source))
        self.assertEqual(result["assessment"], "static-unmeasured")
        self.assertTrue(result["canvas"])
        self.assertTrue(result["webglGpu"])
        self.assertTrue(result["videoTexture"])
        self.assertEqual(result["mediaSlots"]["declaredElements"], 2)
        self.assertEqual(result["dependencySize"]["knownLocalBytes"], 4)
        self.assertTrue(result["guardedProbeRequired"])


class SnapshotTests(unittest.TestCase):
    def test_current_snapshot_is_explicitly_addressable(self) -> None:
        """Current and old explicit IDs resolve to the same immutable bytes."""
        root = str(Path(__file__).resolve().parents[3] / "vendor" / "hyperframes-catalog")
        current = resolve_snapshot(root)
        explicit = resolve_snapshot(root, current.snapshot_id)
        self.assertEqual(current, explicit)
        self.assertTrue(Path(current.index_path).is_file())

    def test_digest_mutation_is_rejected(self) -> None:
        """A registered snapshot cannot change in place."""
        with tempfile.TemporaryDirectory(prefix="catalog-snapshot-", dir="/private/tmp") as tmp:
            source = Path(__file__).resolve().parents[3] / "vendor" / "hyperframes-catalog"
            root = Path(tmp)
            for name in ("catalog-index.json", "hyperframes-catalog-lock.json",
                         "catalog-resource-index-v1.json", "catalog-snapshots-v1.json"):
                (root / name).write_bytes((source / name).read_bytes())
            (root / "catalog-index.json").write_text("[]")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                resolve_snapshot(str(root))

    def test_registry_read_is_bounded_before_json_parsing(self) -> None:
        """An oversized registry cannot become an unbounded planning allocation."""
        with tempfile.TemporaryDirectory(prefix="catalog-registry-", dir="/private/tmp") as tmp:
            root = Path(tmp)
            (root / "catalog-snapshots-v1.json").write_bytes(
                b" " * (MAX_REGISTRY_BYTES + 1))
            with self.assertRaisesRegex(RuntimeError, "bounded read size"):
                resolve_snapshot(str(root))

    def test_index_rows_and_text_are_bounded(self) -> None:
        """Large inventories and individual metadata strings fail closed."""
        with tempfile.TemporaryDirectory(prefix="catalog-index-bounds-", dir="/private/tmp") as tmp:
            path = Path(tmp) / "catalog-index.json"
            row = {"name": "a", "type": "block", "title": "A",
                   "description": "A", "tags": []}
            path.write_text(json.dumps([row] * (MAX_ROWS + 1)))
            with self.assertRaisesRegex(RuntimeError, "exceeds"):
                load_index(str(path))
            row["description"] = "x" * (MAX_TEXT + 1)
            path.write_text(json.dumps([row]))
            records, issues = load_index(str(path))
            self.assertEqual(records, {})
            self.assertIn("description", " ".join(issues))

    def test_resource_and_admission_reads_are_bounded(self) -> None:
        """Refresh metadata never bypasses the same fixed-size read boundary."""
        with tempfile.TemporaryDirectory(prefix="catalog-json-bounds-", dir="/private/tmp") as tmp:
            root = Path(tmp)
            index, lock = root / "catalog-index.json", root / "hyperframes-catalog-lock.json"
            index.write_text("[]")
            lock.write_text("{}")
            resource = root / "catalog-resource-index-v1.json"
            resource.write_bytes(b" " * (MAX_RESOURCE_BYTES + 1))
            rows, issues = load_resource_index(str(resource), str(index), str(lock))
            self.assertEqual(rows, {})
            self.assertIn("bounded read size", " ".join(issues))
            index.write_bytes(b" " * (MAX_METADATA_BYTES + 1))
            with self.assertRaisesRegex(RuntimeError, "bounded read size"):
                inspect_candidate(AdmissionRequest(
                    str(root), str(root), "oversized", "abc123"))

    def test_admission_rejects_a_symlinked_candidate_root(self) -> None:
        """A refresh cannot switch its reviewed directory through a symlink."""
        with tempfile.TemporaryDirectory(prefix="catalog-symlink-", dir="/private/tmp") as tmp:
            root = Path(tmp)
            actual = root / "actual"
            actual.mkdir()
            alias = root / "candidate"
            alias.symlink_to(actual, target_is_directory=True)
            request = AdmissionRequest(str(root), str(alias), "candidate", "abc123")
            with self.assertRaisesRegex(RuntimeError, "regular directory"):
                inspect_candidate(request)

    def test_refresh_admission_requires_exact_commit_and_complete_sources(self) -> None:
        """A future snapshot gets a registry row only from exact complete evidence."""
        with tempfile.TemporaryDirectory(prefix="catalog-admission-", dir="/private/tmp") as tmp:
            root = Path(tmp)
            (root / "compositions" / "components").mkdir(parents=True)
            row = {"name": "proof-card", "type": "component", "title": "Proof Card",
                   "description": "Shows evidence", "tags": ["proof"]}
            (root / "catalog-index.json").write_text(json.dumps([row]))
            lock = {"source": "TEST", "sourceCommit": "abc123", "itemsListed": 1,
                    "itemsInstalled": 1, "knownMissing": []}
            (root / "hyperframes-catalog-lock.json").write_text(json.dumps(lock))
            (root / "compositions/components/proof-card.html").write_text("<div>proof</div>")
            resource = build_resource_index(str(root), str(root / "catalog-index.json"),
                                            str(root / "hyperframes-catalog-lock.json"), [row])
            (root / "catalog-resource-index-v1.json").write_text(json.dumps(resource))
            passed = inspect_candidate(AdmissionRequest(
                str(root), str(root), "pinned-abc123", "abc123"))
            failed = inspect_candidate(AdmissionRequest(
                str(root), str(root), "wrong", "def456"))
        self.assertTrue(passed["ok"])
        self.assertEqual(passed["registryEntry"]["sourceCommit"], "abc123")
        self.assertFalse(failed["ok"])
        self.assertIn("sourceCommit", " ".join(failed["issues"]))


if __name__ == "__main__":
    unittest.main()
