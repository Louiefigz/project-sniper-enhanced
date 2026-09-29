"""Frozen full-catalog semantic search tests for ordinary visual planning."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from planner.ordinary_visual_plan_search import run
from planner.visual_plan_catalog_authority import materialize_catalog_authority


class OrdinaryVisualPlanSearchTests(unittest.TestCase):
    """Searches use all frozen rows and reject drift or malformed intent input."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.authority_temp = tempfile.TemporaryDirectory()
        cls.authority_path = Path(cls.authority_temp.name) / "CATALOG-AUTHORITY.json"
        cls.pin = materialize_catalog_authority(str(cls.authority_path))
        cls.authority_bytes = cls.authority_path.read_bytes()
        cls.authority = json.loads(cls.authority_bytes)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.authority_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "CATALOG-AUTHORITY.json"
        self.context_path = self.root / "VISUAL-PLAN-CONTEXT.json"
        self.query_path = self.root / "VISUAL-SEARCH.json"
        self.output_path = self.root / "VISUAL-SEARCH-RESULTS.json"
        self.catalog_path.write_bytes(self.authority_bytes)
        pin = copy.deepcopy(self.pin)
        pin.update({
            "indexPath": str(self.catalog_path),
            "resourceIndexPath": str(self.catalog_path),
            "indexSha256": hashlib.sha256(self.authority_bytes).hexdigest(),
            "resourceIndexSha256": hashlib.sha256(self.authority_bytes).hexdigest(),
        })
        self.context_path.write_text(json.dumps({
            "schemaVersion": 1,
            "kind": "route-neutral-visual-plan-context",
            "requiredVersion": 1,
            "project": {},
            "catalogPin": pin,
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_query(self, rows: list[dict]) -> None:
        self.query_path.write_text(json.dumps({
            "schemaVersion": 1,
            "scope": "ordinary-visual-semantic-queries",
            "queries": rows,
        }), encoding="utf-8")

    def test_searches_the_complete_372_row_frozen_authority(self) -> None:
        self.assertEqual(self.authority["total"], 372)
        self.assertEqual(len(self.authority["items"]), 372)
        self._write_query([
            {"opportunityId": "opp:proof", "intents": [
                "Show credible proof with a customer metric",
                "Visualize evidence and a concrete result",
            ]},
            {"opportunityId": "opp:process", "intents": [
                "Explain a three step workflow and progression",
            ], "filters": {"limit": 5}},
        ])
        value = run(self.catalog_path, self.context_path,
                    self.query_path, self.output_path)
        self.assertEqual(value["catalog"]["total"], 372)
        self.assertEqual(value["query"]["count"], 2)
        self.assertEqual(len(value["searches"]), 2)
        known = {row["ref"] for row in self.authority["items"]}
        for search in value["searches"]:
            self.assertGreater(search["returned"], 0)
            self.assertTrue(all(row["ref"] in known for row in search["results"]))
            self.assertTrue(all(row["credibility"]["status"] in {"credible", "weak"}
                                for row in search["results"]))
            self.assertLessEqual(search["returned"], 5)
        self.assertEqual(len(value["digest"]), 64)
        self.assertEqual(json.loads(self.output_path.read_text()), value)
        self.assertLessEqual(self.output_path.stat().st_size, 4 * 1024 * 1024)

    def test_catalog_mutation_is_rejected_against_controller_pin(self) -> None:
        self._write_query([{"opportunityId": "opp:proof",
                            "intents": ["Show proof"]}])
        self.catalog_path.write_bytes(self.authority_bytes + b" ")
        with self.assertRaisesRegex(ValueError, "bytes differ from controller context"):
            run(self.catalog_path, self.context_path,
                self.query_path, self.output_path)

    def test_search_covers_every_allowed_longform_opportunity(self) -> None:
        rows = [{"opportunityId": f"opp:{index}",
                 "intents": [f"Explain retained semantic beat {index}"]}
                for index in range(256)]
        self._write_query(rows)
        value = run(self.catalog_path, self.context_path,
                    self.query_path, self.output_path)
        self.assertEqual(value["query"]["count"], 256)
        self.assertEqual([row["opportunityId"] for row in value["searches"]],
                         [row["opportunityId"] for row in rows])
        self.assertLessEqual(self.output_path.stat().st_size, 32 * 1024 * 1024)

    def test_invalid_or_unbounded_query_is_rejected(self) -> None:
        invalid_rows = [
            [{"opportunityId": "opp:bad", "intents": ["one", "two", "three",
                                                          "four", "five"]}],
            [{"opportunityId": "opp:bad", "intents": ["proof"],
              "surprise": True}],
            [{"opportunityId": "opp:bad", "intents": ["proof"],
              "filters": {"limit": 6}}],
            [{"opportunityId": "opp:bad", "intents": ["proof"],
              "filters": {"status": "integrated-measured", "limit": 5}}],
        ]
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                self._write_query(rows)
                with self.assertRaises(ValueError):
                    run(self.catalog_path, self.context_path,
                        self.query_path, self.output_path)


if __name__ == "__main__":
    unittest.main()
