"""Actual cold metadata replay with synthetic TEST native provenance, never media.

The real source-capture/stat, raw-reference, parent and per-frame parsers run.
Every failure target is an exact fixture-owned file, never a dependency.
"""
from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from _source_color_observation_read_fixture import ColdObservationFixture
from guided_source_color_observation_contract import validate_source_color_observations


class ColdObservationReadTests(unittest.TestCase):
    """Prove closed data joins without native launches or original source byte replay."""

    def setUp(self) -> None:
        """Use one explicit TEST original cutoff, not a renewed reader timer."""
        self.time = patch("time.monotonic", return_value=1000.0)
        self.time.start()
        self.addCleanup(self.time.stop)
        self.f = ColdObservationFixture()
        self.addCleanup(self.f.cleanup)

    def test_complete_archived_two_source_replay_is_detached_and_stays_data(self) -> None:
        """An absent active marker and unrelated current PID do not bar historical reads."""
        result = self.f.read()
        self.assertEqual(result, self.f.section)
        self.assertIsNot(result, self.f.section)
        self.assertEqual([row["sourceId"] for row in result["sources"]], ["raw-b", "raw-a"])
        self.assertFalse(Path(self.f.references["reservation"]["path"]).exists())
        for key in ("gamutMeasured", "gradeApplied", "basePictureObserved", "openingApproved", "deliveryApproved"):
            self.assertIs(result[key], False)
        self.assertNotIn("decoderExecutionProved", result)
        result["sources"][0]["records"]["width"] = 100
        self.assertEqual(self.f.section["sources"][0]["records"]["width"], 32)

    def test_does_not_open_sources_active_or_current_tools_or_make_live_owners(self) -> None:
        """Keep the decoder/admission/current-runtime factories completely uncalled."""
        forbidden = {row.path for row in self.f.inputs.verified_media.snapshots}
        forbidden |= {self.f.references["reservation"]["path"], self.f.runtime["dockerPath"], self.f.runtime["dockerSocketPath"]}
        opened, actual = [], os.open
        def tracked(path: object, *args: object, **kwargs: object) -> int:
            """Reject exact forbidden fixture paths before opening any descriptor."""
            self.assertNotIn(str(path), forbidden)
            opened.append(str(path))
            return actual(path, *args, **kwargs)
        with patch("os.open", side_effect=tracked), patch("subprocess.run", side_effect=AssertionError("native")), \
                patch("subprocess.Popen", side_effect=AssertionError("native")), \
                patch("color.grade_project_authority.observe_project", side_effect=AssertionError("source rehash")), \
                patch("headless.container_policy._read_approval", side_effect=AssertionError("current approval")):
            self.f.read()
        self.assertIn(self.f.references["archive"]["path"], opened)
        frames = self.f.sections[0]["artifacts"]["frames"]["path"]
        self.assertEqual(opened.count(frames), 1)

    def test_raw_original_parent_and_admission_constraints_are_not_pure_section_facts(self) -> None:
        """A valid supplied shape cannot assert width beyond actual held admission facts."""
        self.f.sections[0]["records"]["width"] = 64
        archive = json.loads(Path(self.f.references["archive"]["path"]).read_bytes())
        validate_source_color_observations(self.f.section, self.f.staged, archive, self.f.inputs)
        with self.assertRaises(ValueError):
            self.f.read()

    def test_authenticated_parent_history_must_equal_exact_saved_original_project(self) -> None:
        """Rehashed TEST parents cannot replace the actual original project history."""
        self.f.change_record("parents", lambda value: value["projectHistory"].update(history=[{"TEST": "changed history"}]))
        with self.assertRaises(ValueError):
            self.f.read()

    def test_saved_parent_bytes_must_still_match_original_hash(self) -> None:
        """No archival parent or fresh current-parent baseline is invented."""
        path = self.f.root / "project.json"
        self.f.allowed.add(path)
        self.f.replace(path, b'{"history":[]}\n')
        with self.assertRaisesRegex(RuntimeError, "hash|bytes"):
            self.f.read()

    def test_original_observation_summary_cannot_coerce_numeric_types(self) -> None:
        """Equal-valued float width in raw project summary is not original typed evidence."""
        self.f.change_record("observation", lambda value: value["observation"].update(width=32.0))
        with self.assertRaises(ValueError):
            self.f.read()

    def test_original_recorded_inventory_cannot_escape_pipeline_or_omit_root(self) -> None:
        """Historical inventory is a pinned subset, never today's unbounded discovery."""
        for fault in ("outside", "omitted", "duplicate"):
            f = ColdObservationFixture()
            self.addCleanup(f.cleanup)
            def mutate(value: dict) -> None:
                """Change only the named TEST execution record's recorded source list."""
                rows = value["executionSources"]
                if fault == "outside":
                    rows[0]["path"] = str(f.root / "unrecorded/worker.py")
                elif fault == "duplicate":
                    rows.append(deepcopy(rows[0]))
                else:
                    rows[:] = [row for row in rows if not row["path"].endswith("grade_observation_policy.py")]
            f.change_record("execution", mutate)
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                f.read()

    def test_execution_version_tool_invocation_and_cleanup_attestations_are_exact(self) -> None:
        """No V2 relabeling, default tool, warning or success-flag coercion is accepted."""
        mutations = [lambda row: row.update(schemaVersion=2), lambda row: row.update(cleanupVerified=1),
            lambda row: row["worker"]["tool"].update(sha256="8" * 64),
            lambda row: row["worker"]["invocation"]["args"].append("-skip_frame"),
            lambda row: row["worker"]["decoder"].update(stderr="warning"),
            lambda row: row["removal"].update(canonicalAbsenceProved=False),
            lambda row: row["network"]["container"]["dns"].update(resolved=True)]
        for update in mutations:
            f = ColdObservationFixture()
            self.addCleanup(f.cleanup)
            f.change_record("execution", update)
            with self.subTest(update=update), self.assertRaises((ValueError, RuntimeError)):
                f.read()

    def test_command_and_intent_hashes_bind_exact_original_launch(self) -> None:
        """A self-consistent altered execution artifact still needs the original intent."""
        self.f.change_record("execution", lambda row: row.update(launchCommandHash="9" * 64))
        with self.assertRaises(ValueError):
            self.f.read()

    def test_original_archive_reference_cannot_change_path_hash_size_or_extra_fields(self) -> None:
        """The active ref only names original bytes; the separate archive is exact."""
        for key, value in (("sha256", "9" * 64), ("sizeBytes", 1), ("extra", False),
                           ("path", self.f.references["reservation"]["path"])):
            before = deepcopy(self.f.references["archive"])
            self.f.references["archive"][key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                self.f.read()
            self.f.references["archive"] = before


if __name__ == "__main__":
    unittest.main()
