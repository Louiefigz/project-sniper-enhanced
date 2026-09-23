"""Catalog discovery on constructed sources: malformed records, missing files,
historical claims vs current evidence, the capability join through the
EXISTING reader (fresh/missing/stale), identity collisions, aspect mismatch,
and the read-only guarantee."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _common  # noqa: F401  (producer pkg root on sys.path)
from graphics import catalog_discovery as cd
from graphics import catalog_discovery_sources as sources
from graphics import comp_capability_artifact as artifact

_ROW = {"canvas": [1080, 1920], "aspect": "9:16", "fadeClass": "fades-clean",
        "contentBBox": [0, 0, 1079, 1919], "specFields": ["text"],
        "specDefaults": {"text": "TEST"},
        "terminalAlpha": {"maxAlpha8": 0, "meanAlpha8": 0.0}}


def _template(kind: str, width: int, height: int, note: str = "") -> str:
    """Build inert template metadata for the test-owned catalog."""
    return ("<!doctype html>\n<html data-composition-variables='[{\"id\":\"text\","
            "\"type\":\"string\",\"label\":\"Card text\",\"default\":\"TEST\"}]'>\n"
            f"<!-- TEST template {kind}: a comparison card fixture {note} -->\n"
            f"<body><div id=\"{kind}-root\" data-composition-id=\"{kind}\" "
            f"data-width=\"{width}\" data-height=\"{height}\"></div></body></html>\n")


def _item(name: str, kind: str = "component", **extra: object) -> dict:
    """Build a minimal index row with explicit test overrides."""
    return {"name": name, "type": kind, "title": name.replace("-", " ").title(),
            "description": f"A {name} fixture", "tags": ["fixture"], **extra}


def _study(name: str, **extra: object) -> dict:
    """Build a historical study row with explicit test overrides."""
    return {"name": name, "type": "component", "mechanism": "tl.set rows",
            "variables": ["text"], "scrubSafe": True, "selfContained": True,
            "fit": "new:test", "quality": "clean", "aspectFlex": "responsive",
            "port": "P1", **extra}


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        """Prepare test-owned catalog evidence and restore patched roots afterward."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-catalog-discovery-",
                                                dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.catalog_dir = self.root / "catalog"
        (self.catalog_dir / "compositions" / "components").mkdir(parents=True)
        self.motion = self.root / "motion"
        (self.motion / "compositions").mkdir(parents=True)
        for name, body in (("hyperframes.json", "{}"), ("package.json", "{}"),
                           ("index.html", "<div></div>")):
            (self.motion / name).write_text(body)
        self.addCleanup(patch.stopall)
        patch.object(artifact, "MOTION_DIR", str(self.motion)).start()
        patch.object(artifact, "COMPOSITIONS_DIR", str(self.motion / "compositions")).start()
        patch.dict(sources.PORTED_KINDS, {}, clear=True).start()
        self.paths = sources.DiscoveryPaths(
            catalog_dir=str(self.catalog_dir), study_path=str(self.root / "study.json"),
            capability_path=str(self.motion / "comp_capabilities.json"))
        self.write_mirror([_item("count-up"), _item("test-block", "block",
                           dimensions={"width": 1920, "height": 1080}, duration=2.0)],
                          {"itemsListed": 2, "itemsInstalled": 2, "knownMissing": []})
        self.write_source("count-up")
        self.write_source("test-block", "block")
        self.write_study([_study("count-up"), _study("test-block", type="block",
                                                      aspectFlex="16:9-only")])

    def write_mirror(self, index: list, lock: dict) -> None:
        """Write only this fixture's index and recorded lock metadata."""
        (self.catalog_dir / sources.INDEX_NAME).write_text(json.dumps(index))
        (self.catalog_dir / sources.LOCK_NAME).write_text(json.dumps(
            {"source": "TEST registry", "cliVersion": "0.0.0", "mirroredAt": "2026-01-01",
             "files": 0, "boundary": "TEST", **lock}))

    def write_source(self, name: str, kind: str = "component") -> None:
        """Write one inert source into the exact fixture catalog."""
        folder = self.catalog_dir / "compositions" / ("" if kind == "block" else "components")
        (folder / f"{name}.html").write_text(f"<!-- TEST reference {name} -->\n")

    def write_study(self, rows: list) -> None:
        """Write historical metadata into this fixture's study file."""
        (self.root / "study.json").write_text(json.dumps(rows))

    def write_template(self, kind: str, dimensions: tuple[int, int] = (1080, 1920),
                       note: str = "") -> None:
        """Write declared canvas metadata to the fixture-owned template."""
        (self.motion / "compositions" / f"{kind}.html").write_text(
            _template(kind, *dimensions, note))

    def write_artifact(self, rows: dict) -> None:
        """Publish a synthetic artifact through the existing builder."""
        (self.motion / "comp_capabilities.json").write_text(
            json.dumps(artifact.build_artifact(rows)))

    def catalog(self) -> cd.Catalog:
        """Load this fixture through the actual catalog loader."""
        return cd.load_catalog(self.paths)

    def one(self, name: str) -> dict:
        """Return one exact public lookup match."""
        (record,) = cd.lookup_item(self.catalog(), name)["matches"]
        return record


class RecordValidationTests(_Fixture):
    def test_nonfinite_duration_rows_are_reported_and_dropped(self) -> None:
        """Reject nonfinite JSON extensions and overflow without losing valid rows."""
        tokens = ("NaN", "Infinity", "-Infinity", "1e999")
        rows = [_item(f"bad-{index}", duration=token) for index, token in enumerate(tokens)]
        raw = json.dumps([*rows, _item("finite-control", duration=0.5)])
        for token in tokens:
            raw = raw.replace(json.dumps(token), token)
        (self.catalog_dir / sources.INDEX_NAME).write_text(raw)
        catalog = self.catalog()
        self.assertEqual([row["id"] for row in catalog.records], ["finite-control"])
        self.assertEqual(catalog.provenance["issues"], [
            f"index record #{index} dropped: bad-{index}: duration must be a finite positive number"
            for index in range(len(tokens))])
        self.assertIsNone(sources.index_record_issue(_item("positive", duration=0.5)))
        json.dumps(cd.search_catalog(catalog, "finite"), allow_nan=False)

    def test_finite_duration_controls_keep_existing_optional_policy(self) -> None:
        """Retain finite int/float extremes and absent or null duration metadata."""
        rows = [_item(f"control-{index}", duration=value)
                for index, value in enumerate((1, 0.25, 1e308, 5e-324, None))]
        rows.append(_item("absent"))
        self.write_mirror(rows, {"itemsListed": len(rows)})
        records, issues = sources.load_index(str(self.catalog_dir / sources.INDEX_NAME))
        self.assertEqual(list(records.values()), rows)
        self.assertEqual(issues, [])
        json.dumps(records, allow_nan=False)

    def test_malformed_and_duplicate_records_are_reported_not_used(self) -> None:
        """Verify malformed and duplicate records are reported not used."""
        self.write_mirror([_item("count-up"), {**_item("count-up"), "title": "Later Dup"},
                           _item("../escape"), _item("test-widget", "widget"),
                           "not-a-record", {**_item("test-dims"), "dimensions": {"width": -1, "height": 9}}],
                          {"itemsListed": 6, "itemsInstalled": 6,
                           "knownMissing": [{"nope": True}]})
        self.write_study([_study("count-up"), _study("count-up"), {"name": 7}])
        catalog = self.catalog()
        issues = "\n".join(catalog.provenance["issues"])
        for needle in ("duplicate name 'count-up'", "../escape", "type must be",
                       "record is not an object", "positive integers",
                       "knownMissing row ignored", "duplicate 'count-up'", "invalid name 7"):
            self.assertIn(needle, issues)
        self.assertEqual([r["id"] for r in catalog.records], ["count-up"])
        self.assertEqual(catalog.records[0]["title"], "Count Up")
        self.assertIn("lock lists 6 items; the index carries 1",
                      catalog.provenance["disagreements"])

    def test_missing_reference_source_is_a_distinct_status(self) -> None:
        """Verify missing reference source is a distinct status."""
        (self.catalog_dir / "compositions" / "components" / "count-up.html").unlink()
        record = self.one("count-up")
        self.assertEqual(record["integration"]["status"], cd.STATUS_REFERENCE_MISSING)
        self.assertFalse(record["upstream"]["reference"]["exists"])
        self.assertIn("lock does not record it as missing", " ".join(record["disagreements"]))
        self.assertIn("study does not record it as missing", " ".join(record["disagreements"]))
        self.assertTrue(any("nothing to read or port" in n for n in record["adaptationNotes"]))
        result = cd.search_catalog(self.catalog(), "test card")
        self.assertIn("mirror:count-up", [r["ref"] for r in result["results"]])

    def test_historical_study_claim_does_not_override_current_evidence(self) -> None:
        """Verify historical study claim does not override current evidence."""
        self.write_study([_study("count-up", mechanism="FILE MISSING from mirror",
                                 scrubSafe="conditional: unverifiable", selfContained=False,
                                 variables=["CONFIG: color"], fit="unfit:missing file",
                                 port="skip: record as missing", quality="wonky: cannot audit")])
        record = self.one("count-up")
        self.assertEqual(record["integration"]["status"], cd.STATUS_REFERENCE)
        self.assertTrue(record["upstream"]["reference"]["exists"])
        self.assertEqual(record["disagreements"],
                         ["study records FILE MISSING but the source exists on disk"])
        self.assertTrue(record["study"]["mechanism"].startswith("FILE MISSING"))
        notes = " | ".join(record["adaptationNotes"])
        for needle in ("scrub safety", "not self-contained", "CONFIG object",
                       "study fit: unfit", "study port: skip", "study quality: wonky"):
            self.assertIn(needle, notes)

    def test_declared_aspect_sources_and_filter(self) -> None:
        """Verify declared aspect sources and filter."""
        block, card = self.one("test-block"), self.one("count-up")
        self.assertEqual(block["declared"], {"dimensions": [1920, 1080], "aspects": ["16:9"],
                                             "aspectSource": "index-dimensions"})
        self.assertEqual(card["declared"]["aspectSource"], "study-aspectFlex")
        self.assertEqual(card["declared"]["aspects"], ["16:9", "9:16"])
        vertical = cd.search_catalog(self.catalog(), "test",
                                     cd.SearchFilters(declared_aspect="9:16"))
        self.assertEqual([r["ref"] for r in vertical["results"]], ["mirror:count-up"])


class CapabilityJoinTests(_Fixture):
    def setUp(self) -> None:
        """Prepare test-owned catalog evidence and restore patched roots afterward."""
        super().setUp()
        self.write_template("count-up")
        self.write_artifact({"count-up": dict(_ROW)})

    def test_fresh_missing_and_stale_artifacts_through_the_existing_reader(self) -> None:
        """Verify fresh missing and stale artifacts through the existing reader."""
        fresh = self.one("local:count-up")
        self.assertEqual(fresh["integration"]["status"], cd.STATUS_MEASURED)
        self.assertEqual(fresh["integration"]["measured"]["canvas"], [1080, 1920])
        self.assertTrue(self.catalog().provenance["capability"]["fresh"])
        (self.motion / "comp_capabilities.json").unlink()
        missing = self.one("local:count-up")
        self.assertEqual(missing["integration"]["status"], cd.STATUS_UNMEASURED)
        self.assertIn("matrix file missing", missing["integration"]["evidence"])
        self.assertIsNone(missing["integration"]["measured"])
        self.write_artifact({"count-up": dict(_ROW)})
        self.write_template("count-up", note="edited after the probe")
        stale = self.one("local:count-up")
        self.assertEqual(stale["integration"]["status"], cd.STATUS_UNMEASURED)
        self.assertIn("stale", stale["integration"]["evidence"])
        self.assertEqual(stale["integration"]["qualifiedAspects"], [])
        references = cd.search_catalog(self.catalog(), "test block")
        self.assertIn("mirror:test-block", [r["ref"] for r in references["results"]])
        self.assertFalse(references["provenance"]["capability"]["fresh"])

    def test_incomplete_row_is_unmeasured_with_its_reason(self) -> None:
        """Verify incomplete row is unmeasured with its reason."""
        self.write_artifact({"count-up": {**_ROW, "renderError": "TEST probe failed"}})
        record = self.one("local:count-up")
        self.assertEqual(record["integration"]["status"], cd.STATUS_UNMEASURED)
        self.assertIn("render probe failed: TEST probe failed", record["integration"]["evidence"])
        self.assertEqual(self.catalog().provenance["capability"]["incompleteRows"], ["count-up"])

    def test_same_name_is_not_the_same_identity(self) -> None:
        """Verify same name is not the same identity."""
        result = cd.lookup_item(self.catalog(), "count-up")
        self.assertEqual([r["ref"] for r in result["matches"]],
                         ["local:count-up", "mirror:count-up"])
        local, mirror = result["matches"]
        self.assertEqual(local["provenance"], cd.PROVENANCE_LOCAL)
        self.assertIsNone(local["upstream"])
        self.assertEqual(mirror["integration"], {
            "status": cd.STATUS_REFERENCE, "kind": None, "measured": None,
            "qualifiedAspects": [], "evidence": "not integrated; reference source present"})

    def test_port_joins_only_with_declared_provenance(self) -> None:
        """Verify port joins only with declared provenance."""
        with patch.dict(sources.PORTED_KINDS, {"count-up": "count-up"}):
            unverified = self.catalog()
            self.assertIn("does not declare vendor/hyperframes-catalog provenance",
                          " ".join(unverified.provenance["issues"]))
            self.assertEqual(unverified.provenance["ported"], {})
            self.write_template("count-up", note="upstream: vendor/hyperframes-catalog/x")
            self.write_artifact({"count-up": dict(_ROW)})
            joined = self.one("count-up")
            self.assertEqual(joined["provenance"], cd.PROVENANCE_PORTED)
            self.assertEqual(joined["upstream"]["name"], "count-up")
            self.assertEqual(joined["integration"]["status"], cd.STATUS_MEASURED)
        with patch.dict(sources.PORTED_KINDS, {"count-up": "not-indexed"}):
            self.assertIn("upstream name not indexed",
                          " ".join(self.catalog().provenance["issues"]))

    def test_measured_aspect_never_falls_back_to_declared(self) -> None:
        """Verify measured aspect never falls back to declared."""
        self.write_template("count-up", dimensions=(1920, 1080))
        self.write_artifact({"count-up": dict(_ROW)})      # measured 9:16 row
        record = self.one("local:count-up")
        self.assertEqual(record["declared"]["aspects"], ["16:9"])
        self.assertEqual(record["integration"]["measured"]["aspect"], "9:16")
        self.assertEqual(record["integration"]["qualifiedAspects"], ["9:16"])
        by_declared = cd.search_catalog(self.catalog(), "test",
                                        cd.SearchFilters(declared_aspect="16:9"))
        self.assertIn("local:count-up", [r["ref"] for r in by_declared["results"]])
        self.assertTrue(any("not qualified at the other aspect" in note
                            for note in record["adaptationNotes"]))

    def test_discovery_reads_only_and_writes_nothing(self) -> None:
        """Verify discovery reads only and writes nothing."""
        def snapshot() -> list[tuple]:
            """Capture fixture file sizes and modification times without writes."""
            return sorted((path, name, os.stat(os.path.join(path, name)).st_size,
                           os.stat(os.path.join(path, name)).st_mtime_ns)
                          for path, _, files in os.walk(self.root) for name in files)
        before = snapshot()
        catalog = self.catalog()
        cd.search_catalog(catalog, "test card comparison", cd.SearchFilters(limit=5))
        cd.lookup_item(catalog, "count-up")
        self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
