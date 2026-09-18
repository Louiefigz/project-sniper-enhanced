"""Bounded behavior checks for read-only project context and installed inventory."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context as entry
import context_inventory as inventory


class ContextEntryTests(unittest.TestCase):
    """Exercise selection and metadata boundaries without creating production outputs."""

    def setUp(self) -> None:
        """Create a disposable directory containing only tiny fixture metadata."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, name: str, content: str = "{}") -> Path:
        """Write one small fixture, preserving its relative directory shape."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_no_implicit_latest_project(self) -> None:
        """A nearby dated project does not become selected without a path."""
        self.write("artifacts/2099-12-31/LONG-PROJECT.json")
        args = argparse.Namespace(project=None, workflow="auto", probe_tools=False)
        with patch.object(entry, "inventory", return_value={}), patch.object(entry, "REPO", self.root):
            report = entry.build_context(args)
        self.assertEqual(report["project"]["selection"], "none")
        self.assertEqual(report["workflow"], "overview")
        self.assertNotIn("2099", json.dumps(report))

    def test_configured_codex_root_applies_to_instructions_and_skills(self) -> None:
        """A nondefault Codex home supplies both governing instructions and domain skills."""
        configured = self.write("configured-codex/AGENTS.md", "custom instructions").parent
        skill = self.write("configured-codex/skills/hyperframes/SKILL.md", "installed skill")
        with patch.dict(os.environ, {"CODEX_HOME": str(configured / ".." / configured.name)}):
            instructions = entry.instruction_chain(self.root)
            skills = inventory.skill_inventory(self.root)
        self.assertEqual(instructions[0]["path"], str(configured / "AGENTS.md"))
        self.assertIn(str(skill), [row["path"] for row in skills if row["status"] == "readable"])

    def test_selected_scope_and_recorded_claims(self) -> None:
        """Known markers are exposed without secret fields, recursive receipts or approval."""
        self.write("AGENTS.md", "scoped instructions")
        project = self.write("chosen/LONG-PROJECT.json").parent
        self.write("chosen/CLAUDE.md", "scaffold commands")
        self.write("chosen/PREBUILD-REVIEW.json", '{"status":"pass","secret":"TOKEN_SENTINEL"}')
        self.write("chosen/delivery.json", '{"status":"run TOKEN_SENTINEL"}')
        self.write("chosen/export-newest/HANDOFF.md", "do not select automatically")
        self.write("chosen/.env", "TOKEN_SENTINEL")
        before = sorted(str(path) for path in self.root.rglob("*"))
        report = entry.project_context(project)
        self.assertEqual(report["route"], "native-long")
        self.assertEqual(report["files"]["PREBUILD-REVIEW.json"]["recordedStatus"], "pass")
        self.assertIn("CLAUDE.md", report["files"])
        self.assertNotIn("TOKEN_SENTINEL", json.dumps(report))
        self.assertNotIn("export-newest", json.dumps(report))
        self.assertIn("not-checked", report["reviewQualification"])
        self.assertIn(str(self.root / "AGENTS.md"), [row["path"] for row in report["instructions"]])
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_planned_workflow_does_not_relabel_observed_project(self) -> None:
        """An explicit planned route adds its reads while incomplete state remains clear."""
        self.write("index.html", "<html></html>")
        args = argparse.Namespace(project=str(self.root), workflow="native-long", probe_tools=False)
        with patch.object(entry, "inventory", return_value={}):
            report = entry.build_context(args)
        self.assertEqual(report["workflow"], "native-long")
        self.assertEqual(report["project"]["route"], "native-undeclared")
        self.assertTrue(any(row["path"].endswith("NATIVE_LONG_EXPORT.md") for row in report["requiredReads"]))

    def test_container_lists_child_candidates_without_selecting_latest(self) -> None:
        """A brief container points to declared compositions without silently entering one."""
        self.write("BRIEF.md", "project brief")
        self.write("index.html", "old preview")
        source = self.write("source-project/LONG-PROJECT.json").parent
        prepared = self.write("prepared-project-04/LONG-PROJECT.json").parent
        self.write("deeper/not-immediate/SHORT-PROJECT.json")
        (self.root / "linked-project").symlink_to(source, target_is_directory=True)
        report = entry.project_context(self.root)
        scan = report["nativeCandidates"]
        self.assertEqual(report["path"], str(self.root))
        self.assertEqual(report["route"], "native-undeclared")
        self.assertEqual({row["path"] for row in scan["candidates"]}, {str(source), str(prepared)})
        self.assertFalse(scan["truncated"])
        self.assertIn("--project", scan["nextStep"])
        self.assertTrue(all("not selected" in row["qualification"] for row in scan["candidates"]))

    def test_candidate_scan_is_bounded_and_declared_selection_does_not_scan(self) -> None:
        """Candidate enumeration stays bounded and is unnecessary for a declared project."""
        children = [self.root / str(number) for number in range(100)]
        with patch.object(Path, "iterdir", return_value=iter(children)):
            scan = entry.native_candidates(self.root)
        self.assertEqual(scan["entriesInspected"], 64)
        self.assertTrue(scan["truncated"])
        self.write("BRIEF.md", "brief")
        self.write("LONG-PROJECT.json")
        with patch.object(entry, "native_candidates", side_effect=AssertionError("unnecessary scan")):
            report = entry.project_context(self.root)
        self.assertNotIn("nativeCandidates", report)

    def test_shared_native_selector_conflicts_and_symlinks(self) -> None:
        """The discovery route preserves the exporter's exactly-one-contract rule."""
        self.write("LONG-PROJECT.json")
        self.write("SHORT-PROJECT.json")
        self.assertEqual(entry.project_context(self.root)["route"], "native-manifest-conflict")
        (self.root / "SHORT-PROJECT.json").unlink()
        (self.root / "LONG-PROJECT.json").unlink()
        target = self.write("target.json")
        (self.root / "LONG-PROJECT.json").symlink_to(target)
        self.assertEqual(entry.project_context(self.root)["route"], "native-manifest-conflict")

    def test_invalid_native_json_does_not_claim_readable_contract(self) -> None:
        """Malformed declaration stays distinct from absent or unreadable files."""
        self.write("SHORT-PROJECT.json", "{TOKEN_SENTINEL")
        report = entry.project_context(self.root)
        self.assertEqual(report["route"], "native-manifest-invalid")
        self.assertEqual(report["files"]["SHORT-PROJECT.json"]["status"], "invalid-json")
        self.assertNotIn("TOKEN_SENTINEL", json.dumps(report))

    def test_missing_unreadable_and_broken_files_are_distinct(self) -> None:
        """Filesystem errors retain their class without echoing sensitive error messages."""
        missing = self.root / "missing"
        self.assertEqual(inventory.file_record(missing)["status"], "missing")
        link = self.root / "broken"
        link.symlink_to(missing)
        self.assertEqual(inventory.file_record(link)["status"], "broken-link")
        real = self.write("real")
        with patch.object(Path, "open", side_effect=PermissionError("TOKEN_SENTINEL")):
            row = inventory.file_record(real)
        self.assertEqual(row["status"], "unreadable")
        self.assertEqual(row["errorType"], "PermissionError")
        self.assertNotIn("TOKEN_SENTINEL", json.dumps(row))

    def test_missing_selected_directory_returns_bounded_error(self) -> None:
        """An unavailable explicit selection cannot silently become a general inventory."""
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = entry.main(["--project", str(self.root / "TOKEN_SENTINEL")])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["errorType"], "FileNotFoundError")
        self.assertNotIn("TOKEN_SENTINEL", output.getvalue())

    def test_unreadable_directory_does_not_appear_empty(self) -> None:
        """A directory read failure stops explicit selection before capability collection."""
        output = io.StringIO()
        with patch.object(Path, "iterdir", side_effect=PermissionError("TOKEN_SENTINEL")):
            with contextlib.redirect_stderr(output):
                result = entry.main(["--project", str(self.root)])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["errorType"], "PermissionError")

    def test_metadata_size_and_version_allowlists(self) -> None:
        """Large or arbitrary metadata cannot be reflected as a version or status."""
        file = self.write("package.json", '{"version":"TOKEN_SENTINEL"}')
        self.assertIsNone(inventory.package_record(file)["version"])
        with patch.object(inventory, "MAX_METADATA_BYTES", 4):
            row, data = inventory.json_record(file)
        self.assertEqual(row["status"], "too-large")
        self.assertIsNone(data)

    def test_default_inventory_executes_no_programs(self) -> None:
        """The real local loader can inventory without subprocesses or setup calls."""
        with patch.object(subprocess, "run", side_effect=AssertionError("unexpected execution")):
            report = inventory.inventory(entry.REPO, False)
        self.assertEqual(report["catalog"]["status"], "read")
        self.assertIsNone(report["hyperframes"]["selectedRuntime"])
        self.assertTrue(all(row["versionProbe"] == "not-requested" for row in report["tools"]))

    def test_optional_version_probe_is_fixed_bounded_and_redacted(self) -> None:
        """Version probes retain only a numeric version and use no shell."""
        result = subprocess.CompletedProcess([], 0, "v20.1.2 TOKEN_SENTINEL", "")
        with patch.object(inventory.shutil, "which", return_value="/local/node"):
            with patch.object(subprocess, "run", return_value=result) as run:
                row = inventory.tool_record("node", True)
        self.assertEqual(row["version"], "20.1.2")
        self.assertNotIn("TOKEN_SENTINEL", json.dumps(row))
        self.assertEqual(run.call_args.args[0], ["/local/node", "--version"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_optional_version_timeout_is_explicit(self) -> None:
        """A hung local CLI cannot block the entire inventory indefinitely."""
        with patch.object(inventory.shutil, "which", return_value="/local/node"):
            with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 3)):
                row = inventory.tool_record("node", True)
        self.assertEqual(row["versionProbe"], "TimeoutExpired")
        self.assertIsNone(row["version"])

    def test_snapshot_and_current_source_counts_are_independent(self) -> None:
        """A merged local port does not erase its unavailable upstream mirror file."""
        local = self.write("local.html", "local")
        records = [{"ref": "local:effect", "provenance": "local-integrated",
                    "source": {"path": str(local)},
                    "upstream": {"name": "effect", "reference": {
                        "absolutePath": str(self.root / "absent-mirror.html")}}}]
        sources, mirror = inventory.catalog_sources(records)
        self.assertEqual(inventory.source_counts(sources), {"readable": 1})
        self.assertEqual(inventory.source_counts(mirror), {"missing": 1})
        snapshot = inventory.mirror_snapshot({"itemsInstalled": 1, "boundary": "TOKEN_SENTINEL"})
        self.assertEqual(snapshot["itemsInstalled"], 1)
        self.assertNotIn("TOKEN_SENTINEL", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
