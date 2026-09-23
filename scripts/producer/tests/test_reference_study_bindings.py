"""Durable reference choices survive new projects without repeating discovery."""
from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import unittest

from _reference_reuse_fixture import ReuseFixture
from graphics.reference_reuse_cli import execute
from graphics.reference_reuse_map import prepare_map, validate_map
from graphics.reference_study_bindings import export_study_bindings, read_study_bindings


class ReferenceStudyBindingsTests(ReuseFixture):
    """Use real fixture hashes; synthetic inspection text grants no visual approval."""

    def save(self) -> Path:
        """Export one completed project map into the independent study library."""
        file = self.root / "original-map.json"
        self.write_json(file, self.decided())
        target = self.root / "reference_catalog_matches.json"
        self.write_json(target, export_study_bindings(file, self.catalog()))
        return target

    def reuse_request(self, file: Path) -> dict:
        """Change format, project and timing while retaining the same reference need."""
        self.body["format"] = "longform"
        self.body["project"] = str(self.root / "different-landscape-project")
        self.body["studyBindings"] = [{"id": "saved-reference", **self.pin(file)}]
        self.body["shots"][0]["studyMatch"] = {"libraryId": "saved-reference", "matchId": "shot-1"}
        self.body["shots"][0]["cue"] = "New spoken cue at 10:15"
        self.body["shots"][0].pop("query")
        return self.request()

    def test_new_longform_project_reuses_saved_choices_without_search(self) -> None:
        """The old edit can disappear; a new shot still needs its own adaptation decision."""
        file = self.save()
        (self.root / "original-map.json").unlink()
        (self.root / "request.json").unlink()
        self.assertFalse(read_study_bindings(file, self.catalog())["renderApproved"])
        request = self.reuse_request(file)
        with patch("graphics.reference_reuse_map.search_catalog", side_effect=AssertionError("must not search")):
            record = prepare_map(request, self.catalog())
            shot = record["shots"][0]
            self.assertEqual(shot["search"]["source"], "saved-study-binding")
            self.assertEqual(shot["decision"], {"route": "pending"})
            with self.assertRaisesRegex(ValueError, "pending"):
                validate_map(record, self.catalog())
            shot["inspections"] = deepcopy(shot["savedInspections"])
            shot["decision"] = deepcopy(shot["savedDecision"])
            shot["decision"]["route"] = "configure"
            shot["decision"]["pieces"][0]["changes"] = "TEST landscape layout and new spoken cue"
            report = validate_map(record, self.catalog())
        self.assertTrue(report["ready"])
        self.assertFalse(report["renderApproved"])
        self.assertEqual(report["format"], "longform")
        self.assertIn(str(file), report["inputPins"])

    def test_changed_implementation_or_reference_invalidates_saved_inspection(self) -> None:
        """Names cannot conceal changes to the implementation or observed reference."""
        file = self.save()
        source = self.sources / "meter-card.html"
        before = source.read_bytes()
        source.write_text("TEST changed timing")
        with self.assertRaisesRegex(ValueError, "candidate changed"):
            read_study_bindings(file, self.catalog())
        source.write_bytes(before)
        self.reference.write_text("TEST different observed behavior")
        with self.assertRaisesRegex(ValueError, "stale pinned"):
            read_study_bindings(file, self.catalog())

    def test_new_behavior_cannot_borrow_the_old_inspection(self) -> None:
        """A changed visual need must be studied instead of silently reusing a tag."""
        file = self.save()
        self.reuse_request(file)
        self.body["shots"][0]["requiredBehavior"] = "Different motion and reveal mechanism"
        with self.assertRaisesRegex(ValueError, "requiredBehavior differs"):
            self.prepared()

    def test_pending_or_malformed_bindings_cannot_be_saved_or_loaded(self) -> None:
        """A partial review is not durable reusable inspection evidence."""
        file = self.root / "pending.json"
        self.write_json(file, self.prepared())
        with self.assertRaisesRegex(ValueError, "pending"):
            export_study_bindings(file, self.catalog())
        saved = self.save()
        import json
        value = json.loads(saved.read_text())
        value["matches"] = [None]
        self.write_json(saved, value)
        with self.assertRaisesRegex(ValueError, "invalid study match"):
            read_study_bindings(saved, self.catalog())

    def test_cli_exports_and_checks_with_no_render_approval(self) -> None:
        """The user-facing saved-match commands exercise the same library contract."""
        file = self.root / "map.json"
        self.write_json(file, self.decided())
        target = self.root / "saved.json"
        with patch("graphics.reference_reuse_cli.load_catalog", return_value=self.catalog()):
            result, code = execute(Namespace(command="save-study", map=file, output=target))
            self.assertEqual(code, 0)
            self.assertEqual(result["matchCount"], 1)
            result, code = execute(Namespace(command="check-study", map=target))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "study-bindings-current")
        self.assertFalse(result["renderApproved"])


    def test_known_execution_blockers_survive_saved_research(self) -> None:
        """Inspected research remains reusable without promoting it to production."""
        record = self.decided()
        decision = record["shots"][0]["decision"]
        decision.update(route="blocked", prerequisites=[
            {"kind": "adapter", "detail": "TEST native adaptation has not been qualified"}],
            execution={"adapter": "TEST native adaptation", "status": "unverified"})
        file, saved = self.root / "blocked-map.json", self.root / "blocked-study.json"
        self.write_json(file, record)
        self.write_json(saved, export_study_bindings(file, self.catalog()))
        checked = read_study_bindings(saved, self.catalog())
        self.assertEqual(checked["blockedMatches"], ["shot-1"])
        with patch("graphics.reference_reuse_map.search_catalog", side_effect=AssertionError("must not search")):
            reused = prepare_map(self.reuse_request(saved), self.catalog())
        shot = reused["shots"][0]
        self.assertEqual(shot["savedDecision"]["route"], "blocked")
        shot["inspections"] = deepcopy(shot["savedInspections"])
        shot["decision"] = deepcopy(shot["savedDecision"])
        self.assertFalse(validate_map(reused, self.catalog())["ready"])


if __name__ == "__main__":
    unittest.main()
