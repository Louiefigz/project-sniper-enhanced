"""Regression guards for the Studio review/sync lane edge findings
(reviewed 2026-08-28, fixed same day).

Each ``test_bug*`` case originally PINNED observed buggy behavior; the
bugs are fixed and every case now asserts the correct behavior, keeping
its BUG-N marker as the regression label. The remaining cases prove
hardening that was attacked and HELD (serializer forms, NaN gates,
unicode, fail-closed slots).

Findings index (fixed behavior asserted below):
  BUG-1  >4-decimal plan timings: manifest baselines now record the
         view's sec()-projection read-back, so an untouched project is
         clean and --apply writes nothing.
  BUG-2  bool vs 1/1.0 spec edit: type-aware canon equality reports the
         diff; the template contract then refuses the non-boolean loudly
         (nothing written) instead of silently dropping the edit.
  BUG-3  apply pre-checks everything fallible (media.target, writability)
         BEFORE the first write — a refused apply really writes nothing.
  BUG-4  a formatting-only serializer rewrite of index.html classifies as
         "formatting-only rewrite (no effective change)" and rebaselines;
         a real script/text change still blocks.
  BUG-5  unknown/malformed graphic kind raises StudioProjectError, so the
         studio_project CLI keeps its {"status": "refused"} contract.
  BUG-6  preview-server identity requires the hyperframes CLI's preview
         of THIS studio dir on the recorded port — a log tail or another
         project's server never reads as ours.
  S3     deletion apply: baseline lint failures are re-indexed through
         the deletion compaction, so index-shifted preexisting failures
         stay preexisting while a deletion-caused failure still blocks.
"""
import contextlib
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

from studio import StudioProjectError
from studio.project_writer import readback_window, sec
from studio.studio_project import GenerateRequest, generate_project
from studio.studio_project import main as project_main
from studio.studio_server import (
    ServerRecord, command_is_preview, parked_record, read_record,
    record_path, write_record,
)
from studio.studio_sync import main as sync_main
from studio.sync_diff import compute_report, load_state
from studio.sync_model import t4
from studio.view_manifest import unsynced_changes


def _edge_plan() -> dict:
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
            {"kind": "text-element-wide", "outStart": 2.0, "outEnd": 4.5,
             "anchor": "free-band", "reason": "callout", "id": "callout-1",
             "spec": {"text": "Callout copy", "fontSize": 72}},
            {"kind": "glass-lower-third", "outStart": 8.2, "outEnd": 10.7,
             "anchor": "free-band", "reason": "credibility", "id": "lower-3",
             "spec": {"eyebrow": "COACH", "titleBase": "Aaron ",
                      "titleHighlight": "Figueroa", "accent": "#054BC9",
                      "eyebrowDot": True}}],
    }


def _serializer_rewrite(text: str) -> str:
    """Host slots as Studio's DOM serializer writes them: attributes sorted,
    all double-quoted, values JSON entity-encoded (&amp;/&quot;/&#34;)."""
    def redo(match: re.Match) -> str:
        pairs = re.findall(r"([\w-]+)=(?:\"([^\"]*)\"|'([^']*)')",
                           match.group(0))
        parts = []
        for name, dq, sq in sorted(pairs, key=lambda p: (p[0] != "id", p[0])):
            value = dq if dq else sq
            if name == "data-variable-values":
                value = (value.replace("&", "&amp;")
                         .replace('"', "&quot;", 1).replace('"', "&#34;"))
            parts.append(f'{name}="{value}"')
        return "<div " + " ".join(parts) + ">"
    return re.sub(r'<div id="gfx-[^>]*>', redo, text)


def _patch_slot_attr(index_path: str, slot_id: str, attr: str,
                     value: str) -> None:
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


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _remove_slot(index_path: str, slot_id: str) -> None:
    with open(index_path, encoding="utf-8") as handle:
        text = handle.read()
    line = re.search(rf'[ ]*<div id="{slot_id}"[^>]*></div>\n', text).group(0)
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(line, ""))


def _run_sync(args: list) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sync_main(args)
    return code, out.getvalue()


class StudioPureEdgeTests(unittest.TestCase):
    """No-ffmpeg repros of the arithmetic / matcher-level findings."""

    def test_bug1_sec_projection_readback_baseline(self) -> None:
        """BUG-1 regression: ``readback_window`` is exactly what the view
        reads back (start' = sec(start), end' = start' + sec(duration)),
        NOT round(outEnd, 4) — the independent 4-decimal roundings
        accumulate, which is why baselines must record the projection."""
        start, end = 2.12344, 4.24688
        readback_end = t4(float(sec(start)) + float(sec(end - start)))
        self.assertEqual(readback_window(start, end), (2.1234, readback_end))
        self.assertEqual(readback_end, 4.2468)
        self.assertEqual(t4(end), 4.2469)   # projecting raw outEnd differs
        # 4-decimal timings are a fixed point of the projection
        self.assertEqual(readback_window(1.0, 4.2), (1.0, 4.2))

    def test_bug6_preview_identity_requires_dir_and_port(self) -> None:
        """BUG-6 regression: only the hyperframes CLI preview of THIS
        studio dir on the recorded port reads as ours — a log tail and
        another project's preview on a recycled pid never do."""
        ours_dir, ours_port = "/OUR/project/studio", 3991
        for command in (
                "node /x/node_modules/hyperframes/cli.js preview "
                "/OTHER/project/studio --port 3991",
                "tail -f /Users/me/logs/hyperframes/preview-server.log"):
            self.assertFalse(
                command_is_preview(command, ours_dir, ours_port))    # BUG-6
        self.assertTrue(command_is_preview(
            "node /x/node_modules/hyperframes/cli.js preview "
            "/OUR/project/studio --port 3991", ours_dir, ours_port))
        self.assertFalse(command_is_preview(
            "node /x/node_modules/hyperframes/cli.js preview "
            "/OUR/project/studio --port 3991", ours_dir, 3992))

    def test_parked_record_restored_after_exception(self) -> None:
        """HELD: an exception inside a parked operation still restores
        the server record (the finally path works)."""
        tmp = tempfile.mkdtemp(prefix="park-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        record = ServerRecord(port=3990, pid=99999, url="http://x",
                              started_at="t")
        write_record(tmp, record)
        with self.assertRaises(RuntimeError):
            with parked_record(tmp):
                self.assertFalse(os.path.isfile(record_path(tmp)))
                raise RuntimeError("operation crashed")
        self.assertEqual(read_record(tmp), record)


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class StudioEdgeCaseE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="sniper-studio-edge-")
        cls.base = os.path.join(cls.tmp, "base_master.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "color=c=gray:s=1920x1080:d=12:r=30",
             "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
             cls.base], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _build(self, plan: dict | None = None) -> tuple:
        src = tempfile.mkdtemp(prefix="src-", dir=self.tmp)
        base = os.path.join(src, "base_final.mp4")
        shutil.copyfile(self.base, base)
        plan_path = os.path.join(src, "edit_plan.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan or _edge_plan(), handle, indent=1)
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

    # ---------------------------------------------------------------- #

    def test_bug1_untouched_5dec_timing_is_clean(self) -> None:
        """BUG-1 regression: a freshly generated, untouched project with
        >4-decimal plan timings is clean and --apply writes nothing —
        the manifest baseline records the sec()-projection read-back."""
        plan = _edge_plan()
        plan["graphicsTrack"][0]["outStart"] = 2.12344
        plan["graphicsTrack"][0]["outEnd"] = 4.24688
        src, studio = self._build(plan)
        before = _read(os.path.join(src, "edit_plan.json"))
        report = compute_report(load_state(studio))
        self.assertTrue(report.clean)                       # BUG-1
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 0, out)
        self.assertIn('"clean"', out)
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")), before)
        after = self._plan(src)
        self.assertEqual(after["graphicsTrack"][0]["outEnd"], 4.24688)
        self.assertEqual(after["planVersion"], 1)           # no write

    def test_bug2_bool_to_int_edit_reported_never_lost(self) -> None:
        """BUG-2 regression: an eyebrowDot true -> 1 Studio edit produces
        a real diff (type-aware canon equality). The template contract
        then refuses the non-boolean loudly — nothing is written, the
        edit is never silently dropped even when a sibling timing edit
        would otherwise attribute the index.html change."""
        src, studio = self._build()
        index = os.path.join(studio, "index.html")
        _patch_slot_attr(
            index, "gfx-02", "data-variable-values",
            '{"accent":"#054BC9","eyebrow":"COACH","eyebrowDot":1,'
            '"titleBase":"Aaron ","titleHighlight":"Figueroa"}')
        _patch_slot_attr(index, "gfx-01", "data-start", "1.8")
        before = _read(os.path.join(src, "edit_plan.json"))
        report = compute_report(load_state(studio))
        self.assertFalse(report.blockers)
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-02")
        self.assertEqual([(c.key, c.old, c.new) for c in diff.value_changes],
                         [("eyebrowDot", True, 1)])         # BUG-2: seen
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 1, out)
        verdict = json.loads(out)
        self.assertEqual(verdict["status"], "rejected")
        self.assertTrue(any("must be a boolean" in f
                            for f in verdict["newGateFailures"]))
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")), before)
        gfx02 = [d for d in compute_report(load_state(studio)).entry_diffs
                 if d.slot == "gfx-02"]
        self.assertTrue(gfx02)                              # not lost

    def test_bug2b_bool_to_int_edit_alone_reported_not_wedged(self) -> None:
        """BUG-2 regression (solo variant): the same edit alone is a real
        slot diff, not an unattributable-index.html wedge; apply refuses
        it on the boolean contract with nothing written."""
        _, studio = self._build()
        _patch_slot_attr(
            os.path.join(studio, "index.html"), "gfx-02",
            "data-variable-values",
            '{"accent":"#054BC9","eyebrow":"COACH","eyebrowDot":1,'
            '"titleBase":"Aaron ","titleHighlight":"Figueroa"}')
        report = compute_report(load_state(studio))
        self.assertFalse(report.blockers)                   # BUG-2: no wedge
        self.assertTrue([d for d in report.entry_diffs
                         if d.slot == "gfx-02"])
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 1, out)
        self.assertIn("must be a boolean", out)

    def test_bug3_refused_apply_writes_nothing(self) -> None:
        """BUG-3 regression: when the recorded media.target vanishes
        between generation and apply, apply refuses BEFORE the first
        write — plan and manifest untouched, no plan-history snapshot,
        and the studio dir still loads (not wedged)."""
        src, studio = self._build()
        os.remove(os.path.join(src, "base_final.mp4"))  # target; copy stays
        _patch_slot_attr(os.path.join(studio, "index.html"),
                         "gfx-01", "data-start", "1.5")
        before = _read(os.path.join(src, "edit_plan.json"))
        before_manifest = _read(os.path.join(studio, "studio.manifest.json"))
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 2)
        self.assertIn('"refused"', out)
        self.assertIn("is gone", out)
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")),
                         before)                            # BUG-3: no write
        self.assertEqual(_read(os.path.join(studio, "studio.manifest.json")),
                         before_manifest)
        self.assertFalse(os.path.isdir(os.path.join(src, "plan-history")))
        state = load_state(studio)                          # not wedged
        diff = next(d for d in compute_report(state).entry_diffs
                    if d.slot == "gfx-01")
        self.assertEqual(diff.timing_new[0], 1.5)           # edit retained

    def test_bug4_formatting_only_serializer_rewrite_syncs(self) -> None:
        """BUG-4 regression (sync_diff doctrine): Studio's serialization
        details — quoting, entities, attribute order — never read as an
        edit. A formatting-only rewrite classifies as such, apply
        proceeds (rebaselining the hash), and the next sync is clean."""
        src, studio = self._build()
        index = os.path.join(studio, "index.html")
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(_serializer_rewrite(text))
        before = _read(os.path.join(src, "edit_plan.json"))
        report = compute_report(load_state(studio))
        self.assertFalse(report.entry_diffs)
        self.assertFalse(report.blockers)                   # BUG-4
        self.assertTrue(any("formatting-only rewrite" in n
                            for n in report.file_notes))
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 0, out)
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")), before)
        self.assertEqual(unsynced_changes(studio), [])      # rebaselined
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_bug4b_real_script_change_still_blocks(self) -> None:
        """BUG-4 fail-closed direction: a semantic change the slot diff
        cannot see (the body script's timeline duration) must keep the
        unattributable blocker even through a serializer rewrite."""
        _, studio = self._build()
        index = os.path.join(studio, "index.html")
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        text = _serializer_rewrite(text).replace(
            "tl.to({}, { duration: 12 });", "tl.to({}, { duration: 13 });")
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(text)
        report = compute_report(load_state(studio))
        self.assertFalse(report.entry_diffs)
        self.assertTrue(any("cannot be attributed" in b
                            for b in report.blockers))
        code, _ = _run_sync([studio, "--apply"])
        self.assertEqual(code, 2)

    def test_bug5_unknown_kind_is_a_typed_refusal(self) -> None:
        """BUG-5 regression: a missing composition kind surfaces as
        StudioProjectError and the studio_project CLI prints its
        {"status": "refused"} contract; kinds carrying path separators
        or '..' are rejected explicitly."""
        plan = _edge_plan()
        plan["graphicsTrack"][0]["kind"] = "no-such-comp"
        src = tempfile.mkdtemp(prefix="src-", dir=self.tmp)
        base = os.path.join(src, "base_final.mp4")
        shutil.copyfile(self.base, base)
        plan_path = os.path.join(src, "edit_plan.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan, handle)
        studio = os.path.join(src, "studio")
        with self.assertRaises(StudioProjectError) as caught:   # BUG-5
            generate_project(GenerateRequest(plan_path, base, studio))
        self.assertIn("no-such-comp", str(caught.exception))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = project_main([plan_path, base, studio])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "refused")
        for bad in ("../../etc/passwd", "a/b", "..", ""):
            plan["graphicsTrack"][0]["kind"] = bad
            with open(plan_path, "w", encoding="utf-8") as handle:
                json.dump(plan, handle)
            with self.assertRaises(StudioProjectError):
                generate_project(GenerateRequest(plan_path, base, studio))

    def test_s3_deletion_with_shifted_preexisting_applies(self) -> None:
        """S3 regression: a legacy plan carries a preexisting lint ERROR
        on an entry AFTER the deleted one. The failure reappears on the
        candidate under the compacted index; the baseline remap must
        classify it preexisting so the deletion applies."""
        plan = _edge_plan()
        plan["graphicsTrack"].insert(1, {
            "kind": "text-element-wide", "outStart": 5.0, "outEnd": 6.8,
            "anchor": "free-band", "reason": "beat to delete",
            "id": "gone-2", "spec": {"text": "Delete me", "fontSize": 64}})
        del plan["graphicsTrack"][2]["reason"]      # preexisting lint ERROR
        src, studio = self._build(plan)
        _remove_slot(os.path.join(studio, "index.html"), "gfx-02")
        report = compute_report(load_state(studio))
        self.assertEqual([d.label for d in report.deletions], ["gone-2"])
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 0, out)
        summary = json.loads(out)
        self.assertEqual(summary["status"], "applied")
        self.assertEqual(summary["entriesDeleted"], 1)
        self.assertTrue(any("graphicsTrack[1]: missing reason" in f
                            for f in summary["preexistingGateFailures"]))
        track = self._plan(src)["graphicsTrack"]
        self.assertEqual([e.get("id") for e in track],
                         ["callout-1", "lower-3"])
        self.assertTrue(compute_report(load_state(studio)).clean)

    def test_s3_deletion_causing_real_failure_still_blocks(self) -> None:
        """S3 fail-closed direction: deleting an entry whose absence
        opens a produced-intro retention gap is a failure the edit
        CAUSED — it must block with nothing written."""
        plan = _edge_plan()
        plan["target"]["scope"] = "produced"
        plan["cutTrack"] = [{"sourceId": "raw-1", "start": 0.0, "end": 12.0,
                             "speed": 1.0}]
        plan["graphicsTrack"] = [
            {"kind": "text-element-wide", "outStart": s, "outEnd": s + 2.0,
             "anchor": "free-band", "reason": f"beat {i}", "id": f"g-{i}",
             "spec": {"text": f"Beat {i}", "fontSize": 64}}
            for i, s in enumerate((0.5, 3.5, 6.5, 9.5))]
        src, studio = self._build(plan)
        before = _read(os.path.join(src, "edit_plan.json"))
        _remove_slot(os.path.join(studio, "index.html"), "gfx-03")
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 1, out)
        verdict = json.loads(out)
        self.assertEqual(verdict["status"], "rejected")
        self.assertTrue(any("retention ceiling" in f
                            for f in verdict["newGateFailures"]))
        self.assertEqual(_read(os.path.join(src, "edit_plan.json")), before)
        self.assertEqual(len(self._plan(src)["graphicsTrack"]), 4)

    def test_spec_key_removal_reports_a_field_change(self) -> None:
        """A key nulled/dropped in Studio surfaces as FieldChange(old,
        None) — presence is part of the value, never filtered as
        None == None with empty value_changes."""
        _, studio = self._build()
        _patch_slot_attr(
            os.path.join(studio, "index.html"), "gfx-01",
            "data-variable-values", '{"text":"Callout copy","fontSize":null}')
        report = compute_report(load_state(studio))
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-01")
        self.assertEqual([(c.key, c.old, c.new) for c in diff.value_changes],
                         [("fontSize", 72, None)])
        self.assertEqual(diff.new_spec,
                         {"text": "Callout copy", "fontSize": None})

    def test_preview_server_caches_are_runtime_ignored(self) -> None:
        """The preview server's .thumbnails/ and .waveform-cache/ dirs
        are runtime state, not operator additions — invisible to the
        unsynced-edits guard and the sync differ alike."""
        _, studio = self._build()
        for rel in (os.path.join(".thumbnails", "frame-0001.jpg"),
                    os.path.join(".waveform-cache", "v2_base.mp4.json")):
            path = os.path.join(studio, rel)
            os.makedirs(os.path.dirname(path))
            with open(path, "wb") as handle:
                handle.write(b"cache bytes")
        self.assertEqual(unsynced_changes(studio), [])
        report = compute_report(load_state(studio))
        self.assertTrue(report.clean)
        self.assertEqual(report.additions, [])

    # ------------- attacked and HELD (negative findings) ------------- #

    def test_serializer_forms_with_real_edit_parse_and_apply(self) -> None:
        """HELD: double-quoted entity-encoded values (&amp;/&quot;/&#34;),
        sorted attributes, a self-closed slot div and a
        newline inside the attr JSON all parse; the real timing edit
        syncs and applies cleanly through the serializer forms."""
        src, studio = self._build()
        index = os.path.join(studio, "index.html")
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        text = _serializer_rewrite(text)
        text = text.replace('data-start="2"', 'data-start="1.8"')
        tag = re.search(r'<div id="gfx-02"[^>]*>', text).group(0)
        spaced = tag.replace("&#34;titleBase&#34;", "\n&#34;titleBase&#34;")
        self.assertNotEqual(spaced, tag)    # newline really lands in attr
        text = text.replace(tag + "</div>",
                            spaced[:-1] + "/>")     # self-closed slot div
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(text)
        report = compute_report(load_state(studio))
        self.assertFalse(report.blockers)
        self.assertFalse(report.deletions)  # self-closed slot still parses
        diff = next(d for d in report.entry_diffs if d.slot == "gfx-01")
        self.assertEqual(diff.timing_new, (1.8, 4.3))
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self._plan(src)["graphicsTrack"][0]["outStart"], 1.8)

    def test_nan_edits_are_gated(self) -> None:
        """HELD: NaN cannot reach the plan. A NaN spec number is stopped
        by the template contract's finite check; a NaN data-start is
        stopped by the lint window check (chained comparison inverts to
        an error). Nothing is written either way."""
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"), "gfx-01",
                         "data-variable-values",
                         '{"fontSize":NaN,"text":"Callout copy"}')
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 1, out)
        self.assertIn("finite", out)
        src2, studio2 = self._build()
        _patch_slot_attr(os.path.join(studio2, "index.html"), "gfx-01",
                         "data-start", "NaN")
        code2, out2 = _run_sync([studio2, "--apply"])
        self.assertEqual(code2, 1, out2)
        for src_dir in (src, src2):
            with open(os.path.join(src_dir, "edit_plan.json"),
                      encoding="utf-8") as handle:
                self.assertNotIn("NaN", handle.read())

    def test_duplicate_and_retargeted_slots_fail_closed(self) -> None:
        """HELD: a duplicated host slot id and an edited
        data-composition-id both surface as blockers; apply refuses."""
        _, studio = self._build()
        index = os.path.join(studio, "index.html")
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        line = re.search(r'[ ]*<div id="gfx-01"[^>]*></div>\n',
                         text).group(0)
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(text.replace(line, line + line))
        report = compute_report(load_state(studio))
        self.assertTrue(any("duplicate host slot id" in b
                            for b in report.blockers))
        code, _ = _run_sync([studio, "--apply"])
        self.assertEqual(code, 2)
        _, studio2 = self._build()
        _patch_slot_attr(os.path.join(studio2, "index.html"), "gfx-01",
                         "data-composition-id", "gfx-99-swapped")
        report2 = compute_report(load_state(studio2))
        self.assertTrue(any("retargeted" in b for b in report2.blockers))

    def test_unicode_value_edit_round_trips(self) -> None:
        """HELD: curly quotes, bullets and emoji in an edited value parse,
        diff, apply into the plan, and the next sync is clean."""
        src, studio = self._build()
        _patch_slot_attr(os.path.join(studio, "index.html"), "gfx-01",
                         "data-variable-values",
                         '{"fontSize":72,"text":"“Smart” • '
                         'quotes \U0001f3ac"}')
        code, out = _run_sync([studio, "--apply"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self._plan(src)["graphicsTrack"][0]["spec"]["text"],
                         "“Smart” • quotes \U0001f3ac")
        self.assertTrue(compute_report(load_state(studio)).clean)


if __name__ == "__main__":
    unittest.main()
