"""studio sync-back tests — Studio edits diffed/applied into the plan.

Each case generates a real review project (real generator, tiny ffmpeg
base), then simulates Studio by patching ``index.html`` the way the
file-mutations API does (attribute value rewrites), and drives
``studio_sync`` end to end: dry-run report, gate wall, apply, backup,
manifest rebaseline, and the clamp rule (an untouched exit-clamped slot must
never write its clamped end back into the plan).
"""
import contextlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from _common import _HAVE_FFMPEG

from studio.studio_project import GenerateRequest, generate_project
from studio.studio_sync import main as sync_main
from studio.sync_diff import compute_report, load_state
from studio.sync_model import StudioSyncError
from studio.view_manifest import MANIFEST_NAME, unsynced_changes


def _sync_plan() -> dict:
    """Lint-green longform excerpt; entry 3 exit-clamps to the 6.0s seam."""
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "excerpt": True, "scope": "light",
                   "graphicsStyle": "overlay-rich",
                   "graphicsStyleRationale": "dense overlay pass for a "
                   "talking-head excerpt: every beat carries a card"},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 6.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 10.0, "end": 16.0, "speed": 1.0}],
        "graphicsTrack": [
            {"kind": "statement-card", "outStart": 1.0, "outEnd": 4.2,
             "anchor": "own-screen", "reason": "thesis takeover",
             "spec": {"variant": "nateherk",
                      "statements": "More tactics|One system",
                      "statementLands": 1.2}},
            {"kind": "text-element-wide", "outStart": 2.0, "outEnd": 4.5,
             "anchor": "free-band", "reason": "callout over the card",
             "id": "callout-1",
             "spec": {"text": "Callout copy", "fontSize": 72}},
            {"kind": "kinetic-quote-wide", "outStart": 4.0, "outEnd": 6.4,
             "anchor": "own-screen", "reason": "quote dies on the cut",
             "exitOnCut": True,
             "spec": {"words": "More tactics was never the answer",
                      "emphasisWords": "never"}},
            {"kind": "glass-lower-third", "outStart": 8.2, "outEnd": 10.7,
             "anchor": "free-band", "reason": "speaker credibility beat",
             "id": "lower-3",
             "spec": {"eyebrow": "COACH", "titleBase": "Aaron ",
                      "titleHighlight": "Figueroa", "accent": "#054BC9"}}],
    }


def _patch_slot_attr(index_path: str, slot_id: str, attr: str,
                     value: str) -> None:
    """Rewrite one host-slot attribute value, as file-mutations does."""
    with open(index_path, encoding="utf-8") as handle:
        text = handle.read()
    tag = re.search(rf'<div id="{slot_id}"[^>]*>', text).group(0)
    if attr == "data-variable-values":
        new_tag = re.sub(r"data-variable-values='[^']*'",
                         f"data-variable-values='{value}'", tag)
    else:
        new_tag = re.sub(rf'{attr}="[^"]*"', f'{attr}="{value}"', tag)
    assert new_tag != tag, f"patch had no effect on {slot_id}.{attr}"
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(tag, new_tag))


def _remove_slot(index_path: str, slot_id: str) -> None:
    with open(index_path, encoding="utf-8") as handle:
        text = handle.read()
    line = re.search(rf'[ ]*<div id="{slot_id}"[^>]*></div>\n', text).group(0)
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(line, ""))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _run_main(args: list) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sync_main(args)
    return code, out.getvalue()


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class StudioSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="sniper-studio-sync-")
        cls.base = os.path.join(cls.tmp, "base_final.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "color=c=gray:s=1920x1080:d=12:r=30",
             "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
             cls.base], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _build(self, plan: dict | None = None) -> tuple:
        """A fresh (src_dir, studio_dir) pair with a generated project."""
        src = tempfile.mkdtemp(prefix="src-", dir=self.tmp)
        base = os.path.join(src, "base_final.mp4")
        shutil.copyfile(self.base, base)
        plan_path = os.path.join(src, "edit_plan.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan or _sync_plan(), handle, indent=1)
        with open(os.path.join(src, "asset_manifest.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"sources": [{"id": "raw-1", "path": base,
                                    "duration": 20.0}]}, handle)
        studio = os.path.join(src, "studio")
        generate_project(GenerateRequest(plan_path, base, studio))
        return src, studio

    def _plan(self, src: str) -> dict:
        with open(os.path.join(src, "edit_plan.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def _manifest(self, studio: str) -> dict:
        with open(os.path.join(studio, MANIFEST_NAME),
                  encoding="utf-8") as handle:
            return json.load(handle)

    # ------------------------------------------------------------------ #

    def test_untouched_project_is_clean(self) -> None:
        _, studio = self._build()
        report = compute_report(load_state(studio))
        self.assertTrue(report.clean)
        code, out = _run_main([studio])
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_runtime_server_record_is_ignored(self) -> None:
        _, studio = self._build()
        with open(os.path.join(studio, ".studio-server.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"port": 3984, "pid": 1234}, handle)
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_timing_edit_diff_and_apply(self) -> None:
        src, studio = self._build()
        index = os.path.join(studio, "index.html")
        _patch_slot_attr(index, "gfx-01", "data-start", "0.6")
        report = compute_report(load_state(studio))
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-01")
        self.assertEqual(diff.timing_old, (1.0, 4.2))
        self.assertEqual(diff.timing_new, (0.6, 3.8))
        self.assertFalse(report.blockers)
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        plan = self._plan(src)
        self.assertEqual(plan["graphicsTrack"][0]["outStart"], 0.6)
        self.assertEqual(plan["graphicsTrack"][0]["outEnd"], 3.8)
        self.assertEqual(plan["planVersion"], 2)
        history = os.path.join(src, "plan-history")
        backups = os.listdir(history)
        self.assertEqual(len(backups), 1)
        with open(os.path.join(history, backups[0]),
                  encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["planVersion"], 1)
        manifest = self._manifest(studio)
        self.assertEqual(manifest["entries"][0]["outStart"], 0.6)
        self.assertEqual(unsynced_changes(studio), [])
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_variable_edit_including_non_panel_key(self) -> None:
        src, studio = self._build()
        index = os.path.join(studio, "index.html")
        _patch_slot_attr(
            index, "gfx-01", "data-variable-values",
            '{"statementLands":1.0,"statements":"More tactics|One engine",'
            '"variant":"nateherk"}')
        report = compute_report(load_state(studio))
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-01")
        changes = {c.key: (c.old, c.new) for c in diff.value_changes}
        self.assertEqual(changes["statementLands"], (1.2, 1))
        self.assertEqual(changes["statements"][1], "More tactics|One engine")
        self.assertIn("statementLands",
                      self._manifest(studio)["entries"][0]["nonPanelKeys"])
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        spec = self._plan(src)["graphicsTrack"][0]["spec"]
        self.assertEqual(spec["statementLands"], 1)
        self.assertEqual(spec["statements"], "More tactics|One engine")
        self.assertEqual(
            self._manifest(studio)["entries"][0]["nonPanelKeys"],
            ["statementLands"])
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_formatting_only_values_rewrite_is_clean(self) -> None:
        _, studio = self._build()
        _patch_slot_attr(
            os.path.join(studio, "index.html"), "gfx-02",
            "data-variable-values",
            '{"text": "Callout copy", "fontSize": 72.0}')
        report = compute_report(load_state(studio))
        self.assertFalse([d for d in report.entry_diffs if d.plan_facing])

    def test_untouched_clamped_slot_keeps_plan_out_end(self) -> None:
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-02", "data-variable-values",
                         '{"fontSize":80,"text":"Callout copy"}')
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        entry = self._plan(src)["graphicsTrack"][2]
        self.assertEqual(entry["outEnd"], 6.4)      # NOT the 6.0 clamp
        manifest = self._manifest(studio)
        self.assertEqual(manifest["entries"][2]["outEnd"], 6)
        self.assertTrue(manifest["entries"][2]["exitClamped"])
        self.assertEqual(manifest["exitClampedCount"], 1)

    def test_edited_clamped_slot_operator_value_wins(self) -> None:
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-03", "data-start", "4.2")
        report = compute_report(load_state(studio))
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-03")
        self.assertEqual(diff.timing_old, (4.0, 6.0))   # clamped baseline
        self.assertEqual(diff.timing_new, (4.2, 6.2))
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        entry = self._plan(src)["graphicsTrack"][2]
        self.assertEqual((entry["outStart"], entry["outEnd"]), (4.2, 6.2))
        self.assertFalse(self._manifest(studio)["entries"][2]["exitClamped"])

    def test_deletion_removes_entry(self) -> None:
        src, studio = self._build()
        _remove_slot(os.path.join(studio, "index.html"), "gfx-02")
        report = compute_report(load_state(studio))
        self.assertEqual([d.label for d in report.deletions], ["callout-1"])
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        track = self._plan(src)["graphicsTrack"]
        self.assertEqual(len(track), 3)
        self.assertNotIn("callout-1", [e.get("id") for e in track])
        manifest = self._manifest(studio)
        self.assertEqual(len(manifest["entries"]), 3)
        self.assertEqual(unsynced_changes(studio), [])
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_unsupported_index_addition_blocks_and_stays_pending(self) -> None:
        """Unknown hosts cannot be silently adopted, even when a new file exists."""
        _, studio = self._build()
        index = os.path.join(studio, "index.html")
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        addition = ('    <div id="gfx-99" class="clip"'
                    ' data-composition-id="gfx-99-x"'
                    ' data-composition-src="compositions/gfx-99-x.html"'
                    ' data-start="5" data-duration="1" data-track-index="4"'
                    ' style="z-index: 40;"></div>\n')
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(text.replace(
                "  </div>\n  <script>", addition + "  </div>\n  <script>"))
        with open(os.path.join(studio, "compositions", "gfx-99-x.html"),
                  "w", encoding="utf-8") as handle:
            handle.write("<!doctype html><html><body>x</body></html>")
        report = compute_report(load_state(studio))
        self.assertTrue(report.blockers)
        self.assertEqual(len(report.additions), 2)
        self.assertTrue(any("gfx-99" in a for a in report.additions))
        self.assertTrue(any("gfx-99-x.html" in a for a in report.additions))
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 2, out)
        # the addition stays untracked so regeneration still fail-closes
        self.assertTrue(any("unexpected" in c
                            for c in unsynced_changes(studio)))

    def test_instance_file_structural_change_blocks_with_review_note(self) -> None:
        """The advisory is still visible, but unresolved bytes cannot be rebaselined."""
        _, studio = self._build()
        rel = "compositions/gfx-02-text-element-wide.html"
        path = os.path.join(studio, rel)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace("</template>",
                                      "<!-- operator note --></template>"))
        report = compute_report(load_state(studio))
        self.assertTrue(report.blockers)
        note = next(n for n in report.file_notes if n.startswith(rel))
        self.assertIn("structurally edited", note)

    def test_instance_declaration_rewrite_is_machinery_note(self) -> None:
        """A native-serialized default edit is visible and cannot silently sync."""
        src, studio = self._build()
        rel = "compositions/gfx-02-text-element-wide.html"
        path = os.path.join(studio, rel)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        decl = re.search(r'''data-composition-variables=(["'])(.*?)\1''', text, re.DOTALL)
        self.assertIsNotNone(decl)
        rows = json.loads(html.unescape(decl.group(2)))
        next(r for r in rows if r["id"] == "fontSize")["default"] = 96
        replacement = 'data-composition-variables="' + html.escape(json.dumps(rows), quote=True) + '"'
        edited = text.replace(decl.group(0), replacement, 1)
        self.assertNotEqual(edited, text)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(edited)
        report = compute_report(load_state(studio))
        note = next(n for n in report.file_notes if n.startswith(rel))
        self.assertIn("declared-variable defaults", note)
        self.assertTrue(any("unmatched declared default" in item for item in report.blockers))
        before = {file: _read(file) for file in (path, os.path.join(src, "edit_plan.json"),
                                              os.path.join(studio, MANIFEST_NAME))}
        code, output = _run_main([studio, "--apply"])
        self.assertEqual(code, 2, output)
        self.assertEqual({file: _read(file) for file in before}, before)
        self.assertFalse(os.path.exists(os.path.join(src, "plan-history")))

    def test_gate_failure_writes_nothing(self) -> None:
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-01", "data-duration", "0.9")
        before_plan = _read(os.path.join(src, "edit_plan.json"))
        before_manifest = _read(os.path.join(studio, MANIFEST_NAME))
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 1, out)
        verdict = json.loads(out)
        self.assertEqual(verdict["status"], "rejected")
        self.assertFalse(verdict["written"])
        self.assertTrue(verdict["newGateFailures"])
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")),
                         before_plan)
        self.assertEqual(_read(os.path.join(studio, MANIFEST_NAME)),
                         before_manifest)
        self.assertFalse(os.path.isdir(os.path.join(src, "plan-history")))

    def test_legacy_plan_preexisting_failures_do_not_block(self) -> None:
        """Baseline-diff gating: a benign edit syncs on a legacy plan."""
        legacy = _sync_plan()
        del legacy["target"]["excerpt"]      # 12s output < 300s floor: ERROR
        src, studio = self._build(legacy)
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-02", "data-variable-values",
                         '{"fontSize":80,"text":"Callout copy"}')
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        summary = json.loads(out)
        self.assertEqual(summary["status"], "applied")
        self.assertTrue(any("mode floor" in f
                            for f in summary["preexistingGateFailures"]))
        self.assertIn("predates this edit", summary["preexistingNote"])
        spec = self._plan(src)["graphicsTrack"][1]["spec"]
        self.assertEqual(spec["fontSize"], 80)
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_edit_introduced_lint_failure_still_blocks(self) -> None:
        """A NEW failure the edit caused blocks even on a legacy plan."""
        legacy = _sync_plan()
        del legacy["target"]["excerpt"]
        src, studio = self._build(legacy)
        # 11.0 + 3.2 = 14.2s window overruns the 12s output: new lint ERROR
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-01", "data-start", "11")
        before_plan = _read(os.path.join(src, "edit_plan.json"))
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 1, out)
        verdict = json.loads(out)
        self.assertTrue(all("graphicsTrack[0]" in f or "gfx-01" in f
                            for f in verdict["newGateFailures"]))
        self.assertTrue(any("mode floor" in f
                            for f in verdict["preexistingGateFailures"]))
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")),
                         before_plan)
        self.assertFalse(os.path.isdir(os.path.join(src, "plan-history")))

    def test_layout_only_change_is_view_only(self) -> None:
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-01", "data-track-index", "5")
        report = compute_report(load_state(studio))
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-01")
        self.assertFalse(diff.plan_facing)
        self.assertTrue(diff.layout_notes)
        before_plan = _read(os.path.join(src, "edit_plan.json"))
        code, out = _run_main([studio, "--apply"])
        self.assertEqual(code, 0, out)
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")),
                         before_plan)                 # plan untouched
        self.assertEqual(self._manifest(studio)["entries"][0]["track"], 5)
        self.assertEqual(unsynced_changes(studio), [])
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_unattributed_index_change_blocks_apply(self) -> None:
        _, studio = self._build()
        with open(os.path.join(studio, "index.html"), "a",
                  encoding="utf-8") as handle:
            handle.write("<!-- hand edit -->\n")
        report = compute_report(load_state(studio))
        self.assertTrue(any("cannot be attributed" in b
                            for b in report.blockers))
        code, _ = _run_main([studio, "--apply"])
        self.assertEqual(code, 2)

    def test_plan_drift_refuses_sync(self) -> None:
        src, studio = self._build()
        plan = self._plan(src)
        plan["graphicsTrack"][0]["outStart"] = 1.1
        with open(os.path.join(src, "edit_plan.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(plan, handle, indent=1)
        with self.assertRaises(StudioSyncError):
            load_state(studio)
        code, out = _run_main([studio])
        self.assertEqual(code, 2)
        self.assertIn("regenerate", out)


if __name__ == "__main__":
    unittest.main()
