"""Actual installed parser + generated TEMP views; native media/server forbidden."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from test_studio_sync import _sync_plan

from studio import StudioProjectError
from studio import comp_hf_ids, studio_project, sync_apply, sync_files
from studio.project_writer import ReviewBase
from studio.sync_diff import compute_report, load_state
from studio.view_manifest import build_fingerprint, generation_fields, generation_version, unsynced_changes

_SAMPLES = json.loads(Path(__file__).with_name("_studio_hf_ids_samples.json").read_text(encoding="utf8"))


class StudioHfIdsTests(unittest.TestCase):
    """Only the pure installed Node parser may run; base probing is a TEST leaf."""

    def setUp(self) -> None:
        """Create fresh single-link metadata, never mutate a retained source/tool."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-studio-hf-ids-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.plan = self.root / "edit_plan.json"
        self.plan.write_text(json.dumps(_sync_plan()), encoding="utf8")
        self.base = self.root / "base_final.mp4"
        self.base.write_bytes(b"TEST inert base, never probed or rendered")
        self.studio = self.root / "studio"
        self.probe = ReviewBase(1080, 1920, 12.0, 30.0, "", False)
        self.request = studio_project.GenerateRequest(str(self.plan), str(self.base), str(self.studio))
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(studio_project, "_probe_base", return_value=self.probe).start()
        self.allowed: set[Path] = set()

    def _generate(self) -> None:
        """Use the actual generator, then retain an exact TEST mutation allowlist."""
        studio_project.generate_project(self.request)
        self.allowed = {path for path in self.studio.rglob("*") if path.is_file() and not path.is_symlink()}

    def _change(self, file: Path, value: str) -> None:
        """Mutation targets only original canonical TEMP metadata regular files."""
        self.assertIn(file, self.allowed)
        self.assertEqual(file.resolve(), file)
        self.assertTrue(file.is_relative_to(self.root))
        info = file.lstat()
        self.assertTrue(stat.S_ISREG(info.st_mode)); self.assertEqual(info.st_nlink, 1)
        file.write_text(value, encoding="utf8")

    def _legacy(self) -> None:
        """Construct a v1 view before publication with the original unchanged builder."""
        built = studio_project._build_entries(_sync_plan(), self.probe.duration)
        with mock.patch.object(studio_project, "GENERATOR_VERSION", "studio-project-v1"):
            studio_project._write_project(self.request, built, self.probe)
        self.allowed = {path for path in self.studio.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_exact_three_preserved_sdk_samples_one_batch(self) -> None:
        """Original manifest bytes normalize to the exact previously observed SDK save."""
        original = {row["file"]: row["originalHtml"] for row in _SAMPLES["files"]}
        expected = {row["file"]: row["currentHtml"] for row in _SAMPLES["files"]}
        with mock.patch.object(comp_hf_ids, "run_text", wraps=comp_hf_ids.run_text) as run:
            self.assertEqual(comp_hf_ids.normalize_instances(original), expected)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0].stdin_text, "")
        self.assertEqual(original, {row["file"]: row["originalHtml"] for row in _SAMPLES["files"]})

    def test_new_generation_is_stable_and_sdk_open_is_idempotent(self) -> None:
        """The second parser/generator pass cannot dirty a newly sealed v2 view."""
        self._generate()
        state = load_state(str(self.studio))
        self.assertEqual(generation_version(state.manifest, state.fingerprint), "studio-project-v2")
        originals = {entry["file"]: (self.studio / entry["file"]).read_text() for entry in state.manifest["entries"]}
        self.assertEqual(comp_hf_ids.normalize_instances(originals), originals)
        before = {file: file.read_bytes() for file in self.allowed}
        self._generate()
        self.assertEqual({file: file.read_bytes() for file in self.allowed}, before)
        self.assertEqual(unsynced_changes(str(self.studio)), [])
        self.assertTrue(compute_report(load_state(str(self.studio))).clean)

    def test_legacy_rebuild_and_fingerprint_remain_exact_without_node(self) -> None:
        """Old view reconstruction selects no normalization or installed Node path."""
        self._legacy()
        state = load_state(str(self.studio))
        self.assertNotIn("compositionNormalizer", state.manifest)
        file = self.studio / load_state(str(self.studio)).manifest["entries"][0]["file"]
        self._change(file, file.read_text() + "\n<!-- TEST pending old edit -->")
        with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("v1 must not start Node")):
            report = compute_report(load_state(str(self.studio)))
            sync_apply._rewrite_fingerprint(state, state.plan, {})
        self.assertFalse(report.clean)
        self.assertTrue(any("structurally edited" in note for note in report.file_notes))
        self.assertEqual(json.loads((self.studio / "view.fingerprint.json").read_text())["generator"], "studio-project-v1")
        rebuilt = sync_files._rebuild_instance(state.manifest["entries"][0], state.plan["graphicsTrack"][0])
        self.assertEqual(hashlib.sha256(rebuilt.encode()).hexdigest(),
                         state.manifest["files"][state.manifest["entries"][0]["file"]])

    def test_pending_old_view_never_normalizes_or_rebaselines(self) -> None:
        """Unresolved v1 files remain byte-for-byte pending on ordinary generation."""
        self._legacy()
        file = self.studio / load_state(str(self.studio)).manifest["entries"][0]["file"]
        self._change(file, file.read_text() + "\n<!-- TEST pending -->")
        before = {path: path.read_bytes() for path in self.allowed}
        with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("No Node")):
            with self.assertRaisesRegex(StudioProjectError, "unsynced"):
                studio_project.generate_project(self.request)
        self.assertEqual({path: path.read_bytes() for path in self.allowed}, before)

    def test_script_and_text_changes_still_need_brain_review(self) -> None:
        """SDK-owned IDs never waive a genuine code or visible text mutation."""
        self._generate()
        file = self.studio / load_state(str(self.studio)).manifest["entries"][0]["file"]
        original = file.read_text()
        for changed in (original + "\n<script>throw new Error('TEST not executed')</script>",
                        original.replace("You do not need more footage", "Changed TEST meaning")):
            self.assertNotEqual(original, changed)
            self._change(file, changed)
            report = compute_report(load_state(str(self.studio)))
            self.assertFalse(report.clean)
            self.assertTrue(any("structurally edited" in note for note in report.file_notes))

    def test_changed_default_is_blocked_not_normalized_away(self) -> None:
        """No host edit means a changed panel default remains unresolved."""
        self._generate()
        file = self.studio / load_state(str(self.studio)).manifest["entries"][0]["file"]
        original = file.read_text()
        changed = original.replace("&quot;default&quot;: 1.2", "&quot;default&quot;: 1.6", 1)
        self.assertNotEqual(original, changed); self._change(file, changed)
        report = compute_report(load_state(str(self.studio)))
        self.assertTrue(any("unmatched declared default" in error for error in report.blockers))

    def test_unknown_and_mixed_version_metadata_fail_before_node(self) -> None:
        """No directory inference, downgrade, unknown token, or mixed fingerprint."""
        self._generate()
        state = load_state(str(self.studio))
        cases = ({"generator": "studio-project-v9"}, {"generator": "studio-project-v2"},
                 {"generator": "studio-project-v2", "compositionNormalizer": "hf-ids-0.7.33"},
                 {"generator": "studio-project-v1", "compositionNormalizer": "hf-ids-0.8.31"})
        for fields in cases:
            with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("No Node")), \
                    self.subTest(fields=fields), self.assertRaises(StudioProjectError):
                generation_version(fields, state.fingerprint)
        with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("No Node")):
            with self.assertRaisesRegex(StudioProjectError, "differ"):
                generation_version(generation_fields("studio-project-v1"), state.fingerprint)

    def test_changed_new_view_uses_one_rebuild_batch(self) -> None:
        """All changed instances share one SDK parser process."""
        self._generate()
        entries = load_state(str(self.studio)).manifest["entries"]
        self.assertEqual(len(entries), 4)
        for row in entries:
            file = self.studio / row["file"]
            self._change(file, file.read_text() + "\n<!-- TEST pending -->")
        with mock.patch.object(comp_hf_ids, "run_text", wraps=comp_hf_ids.run_text) as run:
            report = compute_report(load_state(str(self.studio)))
        self.assertEqual(run.call_count, 1); self.assertEqual(len(report.file_notes), len(entries))

    def test_mixed_file_metadata_blocks_generation_and_sync_without_node(self) -> None:
        """Validate the actual two retained sidecars, not just detached examples."""
        self._generate()
        target = self.studio / "view.fingerprint.json"
        value = json.loads(target.read_text())
        value.pop("compositionNormalizer"); value["generator"] = "studio-project-v1"
        self._change(target, json.dumps(value))
        before = {file: file.read_bytes() for file in self.allowed}
        with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("No Node")):
            report = compute_report(load_state(str(self.studio)))
            self.assertTrue(any("versions differ" in item for item in report.blockers))
            with self.assertRaisesRegex(StudioProjectError, "versions differ"):
                studio_project.generate_project(self.request)
        self.assertEqual({file: file.read_bytes() for file in self.allowed}, before)

    def test_v2_sync_fingerprint_keeps_original_normalizer_identity(self) -> None:
        """An ordinary plan sync must not downgrade the original generation tag."""
        self._generate()
        state = load_state(str(self.studio))
        sync_apply._rewrite_fingerprint(state, state.plan, {})
        current = json.loads((self.studio / "view.fingerprint.json").read_text())
        self.assertEqual(current, state.fingerprint)

    def test_parser_failure_leaves_no_generation_directory(self) -> None:
        """Fail the prepublication batch, not a partially normalized view."""
        with mock.patch.object(comp_hf_ids, "run_text", side_effect=RuntimeError("TEST parser failed")):
            with self.assertRaisesRegex(RuntimeError, "parser failed"):
                studio_project.generate_project(self.request)
        self.assertFalse(self.studio.exists())

    def test_bounds_reject_before_process(self) -> None:
        """Oversized or non-text generated inputs never reach serialization/SDK."""
        cases = ({}, {"../not-a-comp.html": "x"}, {"compositions/x.html": 3},
                 {"compositions/x.html": "x" * (1024 * 1024 + 1)})
        for value in cases:
            with mock.patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("No Node")), \
                    self.subTest(keys=list(value)), self.assertRaises(StudioProjectError):
                comp_hf_ids.normalize_instances(value)


if __name__ == "__main__":
    unittest.main()
