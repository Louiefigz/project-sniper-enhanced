"""Pending Studio edits: actual generator/SDK parser, inert TEST media only."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_studio_sync as fixtures
from headless.process_runner import ProcessRequest, run_text
from studio import StudioProjectError, comp_hf_ids, studio_project, sync_apply
from studio.project_writer import ReviewBase
from studio.sync_diff import compute_report, load_state
from studio.view_manifest import unsynced_changes

MARKER = "<!-- TEST pending operator note, not executed -->"


def _serialize(text: str) -> str:
    """Use the installed SDK's inert DOM dependency; never execute the saved HTML."""
    script = ("const {createRequire}=require('node:module');"
              "const r=createRequire(require.resolve('@hyperframes/parsers/package.json'));"
              "const {parseHTML}=r('linkedom');"
              "process.stdout.write(parseHTML(require('node:fs').readFileSync(process.argv[1],'utf8')).document.toString());")
    node = comp_hf_ids._node()
    with tempfile.TemporaryDirectory(prefix="sniper-serializer-", dir="/private/tmp") as directory:
        source = Path(directory) / "TEST-input.html"
        source.write_text(text)
        request = ProcessRequest((node, "-e", script, str(source)), "", str(Path(__file__).resolve().parents[3]),
                                 {"PATH": str(Path(node).parent), "LANG": "C.UTF-8"}, 5, max_output_bytes=1 << 20)
        result = run_text(request)
    if result.returncode or result.stderr:
        raise AssertionError(result.stderr)
    return result.stdout


class StudioPendingEditTests(unittest.TestCase):
    """Unsupported bytes remain pending and normal regeneration cannot erase them."""

    def setUp(self) -> None:
        """Use existing genuine generator fixtures with only media probes substituted."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-studio-pending-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        fixture = fixtures.StudioSyncTests()
        fixture.tmp = temporary.name
        fixture.base = str(Path(temporary.name) / "TEST-inert-base.mp4")
        Path(fixture.base).write_bytes(b"TEST inert base; never decoded")
        probe = ReviewBase(1920, 1080, 12.0, 30.0, "", False)
        for target, value in (("studio.studio_project._probe_base", probe),
                              ("studio.index_semantics.probe_media", SimpleNamespace(
                                  width=1920, height=1080, duration=12.0, fps=30.0,
                                  rotation=0, audio_present=False))):
            context = patch(target, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        source, studio = fixture._build()
        self.root, self.studio = Path(source), Path(studio)
        self.index = self.studio / "index.html"
        self.instance = self.studio / "compositions/gfx-02-text-element-wide.html"

    def _snapshot(self) -> dict:
        """Record all original TEST-owned bytes, including plan and private sidecars."""
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def _refused(self) -> None:
        """A refusal cannot publish or make an ordinary regeneration destructive."""
        before = self._snapshot()
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 2, output)
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(unsynced_changes(str(self.studio)))
        request = studio_project.GenerateRequest(str(self.root / "edit_plan.json"),
                                                str(self.root / "base_final.mp4"), str(self.studio))
        with self.assertRaisesRegex(StudioProjectError, "unsynced"):
            studio_project.generate_project(request)
        self.assertEqual(self._snapshot(), before)

    def _timing(self, value: str = "0.6") -> None:
        """Edit the original host attribute using the existing saved-file fixture."""
        fixtures._patch_slot_attr(str(self.index), "gfx-01", "data-start", value)

    def test_structural_instance_note_stays_pending(self) -> None:
        """Original advisory-only loss must refuse before any plan/baseline write."""
        self.instance.write_text(self.instance.read_text() + "\n" + MARKER)
        self._refused()

    def test_valid_timing_cannot_hide_an_index_comment(self) -> None:
        """A recognized slot edit does not authorize unrelated index bytes."""
        self._timing()
        self.index.write_text(self.index.read_text() + "\n" + MARKER)
        self._refused()

    def test_instance_script_text_style_and_defaults_stay_pending(self) -> None:
        """Every unsupported instance body edit stays visible, even beside slot edits."""
        original = self.instance.read_text()
        mutations = (original + "<script>void 'TEST never executed';</script>",
                     original.replace("<body>", '<body style="color: red;">'),
                     original.replace("Callout copy", "Changed TEST copy"),
                     original.replace("&quot;default&quot;: 72", "&quot;default&quot;: 96"))
        self._timing()
        for changed in mutations:
            with self.subTest(change=changed[-80:]):
                self.assertNotEqual(changed, original)
                self.instance.write_text(changed)
                self._refused()

    def test_slot_edit_does_not_hide_script_style_text_or_attribute(self) -> None:
        """Compare the complete original stream, not a boolean slot-diff result."""
        self._timing()
        original = self.index.read_text()
        changes = (original.replace("const errors", "let errors"),
                   original.replace("background: #111", "background: #112"),
                   original.replace("studio review", "Changed TEST title"),
                   original.replace('lang="en"', 'lang="fr"'),
                   original.replace('data-width="1920"', 'data-width="1919"', 1),
                   original.replace("console.error('Sniper Studio", "console.error('Sniper  Studio"))
        for changed in changes:
            with self.subTest(change=changed[-100:]):
                self.assertNotEqual(changed, original)
                self.index.write_text(changed)
                self._refused()

    def test_index_only_new_slot_keeps_pending_without_a_new_file(self) -> None:
        """An added host pointing at an existing composition must not disappear."""
        original = self.index.read_text()
        host = re.search(r'<div id="gfx-02"[^>]*></div>', original).group(0)
        addition = host.replace('id="gfx-02"', 'id="gfx-99"').replace("hf-slot-gfx-02", "hf-slot-gfx-99")
        self.index.write_text(original.replace("  </div>\n  <script>", addition + "  </div>\n  <script>"))
        self._refused()

    def test_real_serializer_repeated_timing_and_view_only_layout(self) -> None:
        """Serialization and exact legacy class/lane/z changes continue to apply."""
        for value in ("0.6", "0.8"):
            self._timing(value)
            text = _serialize(self.index.read_text())
            text = text.replace('class="clip" data-composition-id="gfx-01',
                                'class="clip selected" data-composition-id="gfx-01')
            self.index.write_text(text)
            saved = self.index.read_bytes()
            code, output = fixtures._run_main([str(self.studio), "--apply"])
            self.assertEqual(code, 0, output)
            self.assertEqual(self.index.read_bytes(), saved)
            self.assertEqual(unsynced_changes(str(self.studio)), [])
            self.assertFalse(compute_report(load_state(str(self.studio))).blockers)

    def test_deletion_preserves_saved_bytes_then_allows_another_edit(self) -> None:
        """Remove only authenticated bindings; later sync uses the surviving baseline."""
        fixtures._remove_slot(str(self.index), "gfx-02")
        before = self.index.read_text()
        original_binding = '["gfx-02", "gfx-02-text-element-wide", "compositions/gfx-02-text-element-wide.html"], '
        self.assertIn(original_binding, before)
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.index.read_text(), before.replace(original_binding, "", 1))
        self.assertEqual(unsynced_changes(str(self.studio)), [])
        self._timing()
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertTrue(compute_report(load_state(str(self.studio))).clean)

    def test_deletion_with_modified_bindings_writes_nothing(self) -> None:
        """A caller cannot edit generator script under cover of deleting its host."""
        fixtures._remove_slot(str(self.index), "gfx-02")
        self.index.write_text(self.index.read_text().replace("const bindings", "let bindings"))
        self._refused()

    def test_deleted_host_does_not_authorize_its_changed_instance(self) -> None:
        """A residual note inside a retained deleted composition still needs review."""
        fixtures._remove_slot(str(self.index), "gfx-02")
        self.instance.write_text(self.instance.read_text() + MARKER)
        self._refused()

    def test_last_split_text_deletion_preserves_original_head_choice(self) -> None:
        """A deleted last user does not turn its original head script into a later edit."""
        fixtures._remove_slot(str(self.index), "gfx-01")
        saved_head = self.index.read_text().split("</head>")[0]
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        manifest = json.loads((self.studio / "studio.manifest.json").read_text())
        self.assertIs(manifest["indexNeedsSplitText"], True)
        self.assertEqual(self.index.read_text().split("</head>")[0], saved_head)
        fixtures._patch_slot_attr(str(self.index), "gfx-02", "data-start", "1.9")
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertEqual(unsynced_changes(str(self.studio)), [])

    def test_tampered_or_nonboolean_head_metadata_refuses(self) -> None:
        """Numeric/bool coercion or a guessed head dependency cannot waive residuals."""
        path = self.studio / "studio.manifest.json"
        original = json.loads(path.read_text())
        self._timing()
        for value in (False, 0, 1, "true", None, {}):
            with self.subTest(value=value):
                path.write_text(json.dumps({**original, "indexNeedsSplitText": value}))
                self._refused()

    def test_missing_original_head_record_after_deletion_is_not_guessed(self) -> None:
        """An already-rebaselined old deletion has no inferred recovery or migration."""
        fixtures._remove_slot(str(self.index), "gfx-01")
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        path = self.studio / "studio.manifest.json"
        value = json.loads(path.read_text())
        del value["indexNeedsSplitText"]
        path.write_text(json.dumps(value))
        fixtures._patch_slot_attr(str(self.index), "gfx-02", "data-start", "1.9")
        self._refused()

    def test_late_index_change_refuses_before_first_publication(self) -> None:
        """The prewrite check retains a new save after complete residual validation."""
        fixtures._remove_slot(str(self.index), "gfx-02")
        before = self._snapshot()
        original = sync_apply._check_writable

        def late(state: object, changed: bool) -> None:
            """Only TEST-owned index bytes change at the last prewrite dependency."""
            original(state, changed)
            self.index.write_text(self.index.read_text() + MARKER)

        with patch.object(sync_apply, "_check_writable", side_effect=late):
            code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 2, output)
        before["studio/index.html"] += MARKER.encode()
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(unsynced_changes(str(self.studio)))

    def test_exact_class_track_z_changes_do_not_authorize_other_style(self) -> None:
        """Legacy view-only values survive without admitting extra style properties."""
        for key, value in (("class", "clip selected"), ("data-track-index", "5"), ("style", "z-index: 50;")):
            fixtures._patch_slot_attr(str(self.index), "gfx-01", key, value)
        saved = self.index.read_bytes()
        plan = (self.root / "edit_plan.json").read_bytes()
        code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.index.read_bytes(), saved)
        self.assertEqual((self.root / "edit_plan.json").read_bytes(), plan)
        fixtures._patch_slot_attr(str(self.index), "gfx-01", "style", "z-index: 50; opacity: 0.5;")
        self._refused()

    def test_v1_missing_head_field_reconstructs_without_normalizing_instances(self) -> None:
        """A genuine newly staged old-format view keeps its version after valid sync."""
        self.studio = self.root / "legacy-studio"
        self.index = self.studio / "index.html"
        request = studio_project.GenerateRequest(str(self.root / "edit_plan.json"),
                                                str(self.root / "base_final.mp4"), str(self.studio))
        built = studio_project._build_entries(fixtures._sync_plan(), 12.0)
        probe = ReviewBase(1920, 1080, 12.0, 30.0, "", False)
        with patch.object(studio_project, "GENERATOR_VERSION", "studio-project-v1"):
            studio_project._write_project(request, built, probe)
        self.assertNotIn("indexNeedsSplitText", json.loads((self.studio / "studio.manifest.json").read_text()))
        self._timing()
        with patch.object(comp_hf_ids, "normalize_instances", side_effect=AssertionError("no v1 normalization")):
            code, output = fixtures._run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        manifest = json.loads((self.studio / "studio.manifest.json").read_text())
        self.assertEqual(manifest["generator"], "studio-project-v1")
        self.assertNotIn("compositionNormalizer", manifest)
        self.assertIs(manifest["indexNeedsSplitText"], True)

    def test_index_processing_instructions_and_extra_doctypes_stay_pending(self) -> None:
        """No ignored HTMLParser callback may erase an unsupported saved addition."""
        original = self.index.read_text()
        for addition in ("<?TEST preserve this?>", "<!DOCTYPE html>", "<!DOCTYPE svg>"):
            with self.subTest(addition=addition):
                self.index.write_text(original + addition)
                self._refused()


if __name__ == "__main__":
    unittest.main()
