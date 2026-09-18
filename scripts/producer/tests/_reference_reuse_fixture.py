"""Small inert on-disk catalog and request evidence for reuse-map contracts."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cut_preview_io import file_hash
from graphics.catalog_discovery import Catalog, load_catalog
from graphics.catalog_discovery_sources import DiscoveryPaths
from graphics import comp_capability_artifact as artifact
from graphics.reference_reuse_map import prepare_map


class ReuseFixture(unittest.TestCase):
    """Exercise real discovery and hashing with test-owned source files."""

    def setUp(self) -> None:
        """Create two reference candidates without any media execution."""
        temporary = tempfile.TemporaryDirectory(prefix="reference-reuse-test-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.catalog_root = self.root / "catalog"
        self.sources = self.catalog_root / "compositions" / "components"
        self.sources.mkdir(parents=True)
        self.motion = self.root / "motion"
        self.motion.mkdir()
        patcher = patch.object(artifact, "COMPOSITIONS_DIR", str(self.motion))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.paths = DiscoveryPaths(str(self.catalog_root), str(self.root / "study.json"),
                                    str(self.root / "missing-capability.json"))
        self.index = [{"name": name, "type": "component", "title": name,
                       "description": "A comparison card", "tags": ["comparison"],
                       "dimensions": {"width": 1920, "height": 1080}}
                      for name in ("meter-card", "callout-card")]
        self.write_json(self.catalog_root / "catalog-index.json", self.index)
        self.write_json(self.catalog_root / "hyperframes-catalog-lock.json",
                        {"itemsListed": 2, "itemsInstalled": 2, "knownMissing": []})
        self.write_json(self.root / "study.json", [])
        for name in ("meter-card", "callout-card"):
            (self.sources / f"{name}.html").write_text(f"<!-- TEST ONLY {name} -->")
        self.reference = self.root / "reference.md"
        self.reference.write_text("TEST beat 03: reveal measured count after spoken promise")
        self.plan = self.root / "shots.md"
        self.plan.write_text("TEST shot-1: count reveal, shot-2: result card")
        self.body = {"scope": "reference-match", "format": "short",
                     "project": str(self.root / "planned-project"),
                     "references": [{"id": "reference-1", **self.pin(self.reference)}],
                     "shotPlan": self.pin(self.plan), "shots": [self.shot("shot-1")]}

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        """Write one test-owned JSON input."""
        path.write_text(json.dumps(value))

    @staticmethod
    def pin(path: Path) -> dict:
        """Return a real input hash, never fabricated verification evidence."""
        return {"path": str(path), "sha256": file_hash(path)}

    @staticmethod
    def shot(identifier: str) -> dict:
        """An explicit reference-driven target shot with stable identity."""
        return {"id": identifier, "referenceId": "reference-1", "referenceBeat": "beat-03",
                "cue": "spoken count", "visualNeed": "make the result legible",
                "requiredBehavior": "reveal count after spoken promise", "query": "comparison card"}

    def request(self) -> dict:
        """Publish the test request body and attach its external self pin."""
        path = self.root / "request.json"
        self.write_json(path, self.body)
        return {**self.body, "request": self.pin(path)}

    def catalog(self) -> Catalog:
        """Use production discovery on this fixture's tiny catalog."""
        return load_catalog(self.paths)

    def prepared(self) -> dict:
        """Create a fresh pending artifact with real on-disk input pins."""
        return prepare_map(self.request(), self.catalog())

    @staticmethod
    def inspect(record: dict, ref: str, fit: str = "usable") -> dict:
        """Provide an explicitly synthetic agent assessment for contract tests."""
        return {"ref": ref, "candidateSha256": record["candidates"][ref]["sha256"],
                "observation": "TEST source inspection: count enters as a whole",
                "fit": fit, "limitations": "TEST lacks per-digit staging"}

    def decided(self, route: str = "reuse") -> dict:
        """Complete the minimum structural decision without claiming visual QA."""
        record = self.prepared()
        shot = record["shots"][0]
        refs = shot["candidateRefs"][:2] if route == "compose" else shot["candidateRefs"][:1]
        shot["inspections"] = [self.inspect(record, ref) for ref in refs]
        shot["decision"] = {"route": route, "reason": "TEST maps the count reveal",
                            "pieces": [{"ref": ref, "role": "count reveal",
                                        "changes": "adjust font" if route == "configure" else ""}
                                       for ref in refs], "prerequisites": [],
                            "execution": {"adapter": "TEST native authoring", "status": "available"}}
        return record

    def custom(self) -> dict:
        """A custom addition keeps one usable piece and compares an inspected gap."""
        record = self.decided()
        shot = record["shots"][0]
        closest = shot["candidateRefs"][1]
        inspection = self.inspect(record, closest, "gap")
        inspection["gapType"] = "missing-capability"
        shot["inspections"].append(inspection)
        decision = shot["decision"]
        decision["route"] = "custom"
        decision["custom"] = {"gapType": "missing-capability", "gap": "TEST digit staging missing",
                              "scope": "TEST animate only the digit reveal",
                              "closest": [{"ref": closest, "reason": "TEST only whole-label reveal"}],
                              "retainedRefs": [piece["ref"] for piece in decision["pieces"]],
                              "retainedPiecesRationale": "TEST retain existing result-card layout"}
        return record
