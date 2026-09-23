"""studio tests — the Studio review-project generator (view lane).

Covers the deterministic surface: lane assignment, the comp→instance
transform (template wrap, id rewrite, timeline re-key, seeded declarations),
the exit-on-cut clamp projection, manifest/fingerprint round-trip, and the
unsynced-edits overwrite guard. The ffmpeg-backed cases build a tiny solid
base clip; Studio server behavior is exercised by the empirical acceptance
run, not here.
"""
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
from studio.comp_transform import (
    InstancePlan,
    build_instance,
    parse_source_comp,
    seed_declarations,
)
from studio.lane_layout import assign_lanes
from studio.studio_project import GenerateRequest, generate_project, main
from studio.view_manifest import (
    FINGERPRINT_NAME,
    MANIFEST_NAME,
    unsynced_changes,
)

_COMPS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "..", "templates",
    "motion", "compositions")
_TEMPLATE_RE = re.compile(r"<template>(?P<inner>.*)</template>", re.DOTALL)
_DECLS_RE = re.compile(
    r"data-composition-variables='(?P<body>[^']*)'", re.DOTALL)


def _comp_html(kind: str) -> str:
    with open(os.path.join(_COMPS, f"{kind}.html"), encoding="utf-8") as f:
        return f.read()


def _studio_plan() -> dict:
    """3 real catalog entries; entries 1+2 overlap (lane split), entry 3 exit-clamps."""
    return {
        "planVersion": 1,
        "target": {"mode": "short"},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 6.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 10.0, "end": 16.0, "speed": 1.0},
        ],
        "graphicsTrack": [
            {"kind": "line-swap", "outStart": 1.0, "outEnd": 3.5,
             "anchor": "own-screen", "reason": "thesis takeover",
             "spec": {"lineA": "More tactics", "lineB": "One system",
                      "swapAt": 1.2, "underlineWord": ""}},
            {"kind": "marker-highlight", "outStart": 2.0, "outEnd": 4.5,
             "anchor": "free-band", "reason": "callout over the card",
             "id": "callout-1",
             "spec": {"text": "Callout copy", "emphasisWord": "copy",
                      "drawAt": 1, "style": "highlight"}},
            {"kind": "marker-highlight", "outStart": 4.0, "outEnd": 9.0,
             "anchor": "own-screen", "reason": "quote dies on the cut",
             "exitOnCut": True,
             "spec": {"text": "More tactics was never the answer",
                      "emphasisWord": "never", "drawAt": 1}},
        ],
    }


def _make_base(path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=gray:s=1080x1920:d=12:r=30",
         "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p", path],
        check=True)


class LaneLayoutTests(unittest.TestCase):
    def test_overlap_splits_disjoint_reuses(self) -> None:
        slots = assign_lanes([(1.0, 3.5), (2.0, 4.5), (4.0, 6.0)])
        self.assertEqual([s.track for s in slots], [1, 2, 1])
        self.assertEqual([s.z_index for s in slots], [10, 20, 10])

    def test_same_lane_never_overlaps(self) -> None:
        windows = [(0.0, 2.0), (1.0, 3.0), (2.5, 4.0), (0.5, 5.0), (4.5, 6.0)]
        slots = assign_lanes(windows)
        by_track: dict[int, list] = {}
        for (start, end), slot in zip(windows, slots):
            by_track.setdefault(slot.track, []).append((start, end))
        for spans in by_track.values():
            spans.sort()
            for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
                self.assertLessEqual(prev_end, next_start + 1e-6)

    def test_non_positive_window_fails(self) -> None:
        with self.assertRaises(StudioProjectError):
            assign_lanes([(2.0, 2.0)])


class CompTransformTests(unittest.TestCase):
    def _build(self, kind: str, spec: dict, duration: float = 2.5):
        source = parse_source_comp(kind, _comp_html(kind))
        return source, build_instance(source, InstancePlan(
            instance_id=f"gfx-01-{kind}", spec=spec, duration=duration))

    def test_line_swap_instance_contract(self) -> None:
        spec = {"lineA": "More tactics", "lineB": "One system",
                "swapAt": 1.2, "underlineWord": ""}
        _, built = self._build("line-swap", spec)
        inner = _TEMPLATE_RE.search(built.html)
        self.assertIsNotNone(inner, "instance must be template-wrapped")
        body = inner.group("inner")
        # id consistency: root id == __timelines key == instance id
        self.assertIn('data-composition-id="gfx-01-line-swap"', body)
        self.assertIn('__timelines["gfx-01-line-swap"]', body)
        self.assertNotIn('__timelines["line-swap"]', body)
        # root gains data-start + the window duration
        root = re.search(r'<[^>]*data-composition-id="gfx-01-line-swap"'
                         r'[^>]*>', body).group(0)
        self.assertIn('data-start="0"', root)
        self.assertIn('data-duration="2.5"', root)
        # functional payload (style + script) lives INSIDE the template
        self.assertIn("<style>", body)
        self.assertIn("<script>", body)
        # html/body page rules are retargeted onto the comp root
        self.assertNotRegex(body, r"[};>]\s*html,\s*body\s*\{")
        self.assertIn("#ls-root {", body)

    def test_declarations_seeded_from_spec(self) -> None:
        spec = {"lineA": "More tactics", "lineB": "One system",
                "swapAt": 1.2, "underlineWord": ""}
        _, built = self._build("line-swap", spec)
        decls_raw = _DECLS_RE.search(built.html).group("body")
        # Studio lint JSON.parses the RAW attribute text — it must carry no
        # HTML entities (verified live: &quot; escaping is a lint ERROR).
        self.assertNotIn("&quot;", decls_raw)
        rows = json.loads(decls_raw)
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["lineA"]["default"], "More tactics")
        self.assertEqual(by_id["swapAt"]["default"], 1.2)
        self.assertEqual(built.non_panel_keys, ())

    def test_non_scalar_spec_value_is_non_panel(self) -> None:
        # Pure declaration behavior, not an invalid executable catalog spec.
        variables = {"cues": {"id": "cues", "type": "string", "default": ""}}
        declarations, non_panel = seed_declarations(variables, {"cues": [1.0, 2.0]})
        self.assertEqual(non_panel, ("cues",))
        self.assertEqual(json.loads(declarations)[0]["default"], "")

    def test_unrewritable_timeline_registration_fails(self) -> None:
        fake = _comp_html("marker-highlight").replace(
            '__timelines["marker-highlight"]', "__timelines[key]")
        source = parse_source_comp("marker-highlight", fake)
        with self.assertRaisesRegex(StudioProjectError, "cannot rewrite"):
            build_instance(source, InstancePlan(
                instance_id="gfx-01-marker-highlight",
                spec={"text": "Callout copy", "emphasisWord": "copy",
                      "drawAt": 1}, duration=2.0))


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class StudioProjectE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="sniper-studio-test-")
        cls.base = os.path.join(cls.tmp, "base_final.mp4")
        _make_base(cls.base)
        cls.plan_path = os.path.join(cls.tmp, "edit_plan.json")
        with open(cls.plan_path, "w", encoding="utf-8") as handle:
            json.dump(_studio_plan(), handle)
        cls.out = os.path.join(cls.tmp, "studio")
        cls.result = generate_project(GenerateRequest(
            cls.plan_path, cls.base, cls.out))
        with open(os.path.join(cls.out, "index.html"),
                  encoding="utf-8") as handle:
            cls.index = handle.read()
        with open(os.path.join(cls.out, MANIFEST_NAME),
                  encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_project_structure(self) -> None:
        for rel in ("index.html", "hyperframes.json", "STORYBOARD.md",
                    FINGERPRINT_NAME, MANIFEST_NAME,
                    "compositions/gfx-01-line-swap.html",
                    "compositions/gfx-02-marker-highlight.html",
                    "compositions/gfx-03-marker-highlight.html",
                    "assets/tokens.css", "assets/vendor/gsap.min.js"):
            self.assertTrue(
                os.path.isfile(os.path.join(self.out, rel)), rel)
        # Studio's file server refuses symlinks (verified live) — the base
        # must be a real copy.
        staged = os.path.join(self.out, "assets", "base.mp4")
        self.assertTrue(os.path.isfile(staged) and not os.path.islink(staged))
        self.assertEqual(os.path.getsize(staged), os.path.getsize(self.base))

    def test_root_matches_probed_video(self) -> None:
        root = re.search(r'<div id="review-root"[^>]*>', self.index).group(0)
        self.assertIn('data-width="1080"', root)
        self.assertIn('data-height="1920"', root)
        self.assertIn('data-duration="12"', root)
        self.assertIn('data-start="0"', root)
        video = re.search(r"<video[^>]*>", self.index).group(0)
        self.assertIn('data-track-index="0"', video)
        self.assertIn("muted", video)
        # solid test clip has no audio stream -> no review audio element
        self.assertNotIn("<audio", self.index)

    def test_slot_attributes_and_values(self) -> None:
        slot = re.search(r'<div id="gfx-01"[^>]*>', self.index).group(0)
        self.assertIn('data-composition-id="gfx-01-line-swap"', slot)
        self.assertIn(
            'data-composition-src="compositions/gfx-01-line-swap.html"',
            slot)
        self.assertIn('data-start="1"', slot)
        self.assertIn('data-duration="2.5"', slot)
        self.assertIn('data-width="1080"', slot)
        self.assertIn('data-height="1920"', slot)
        values = re.search(r"data-variable-values='([^']*)'", slot).group(1)
        self.assertNotIn("&quot;", values)  # raw JSON, lint-parseable
        decoded = json.loads(values)
        self.assertEqual(decoded, {"lineA": "More tactics", "lineB": "One system",
                                   "swapAt": 1.2, "underlineWord": ""})

    def test_id_consistency_host_root_timeline(self) -> None:
        for slot_id in ("gfx-01", "gfx-02", "gfx-03"):
            slot = re.search(
                rf'<div id="{slot_id}"[^>]*>', self.index).group(0)
            comp_id = re.search(
                r'data-composition-id="([^"]*)"', slot).group(1)
            src = re.search(r'data-composition-src="([^"]*)"', slot).group(1)
            with open(os.path.join(self.out, src),
                      encoding="utf-8") as handle:
                instance = handle.read()
            inner = _TEMPLATE_RE.search(instance).group("inner")
            self.assertIn(f'data-composition-id="{comp_id}"', inner)
            self.assertIn(f'__timelines["{comp_id}"]', inner)

    def test_lane_assignment_in_index(self) -> None:
        tracks = {slot_id: re.search(
            rf'<div id="{slot_id}"[^>]*data-track-index="(\d+)"',
            self.index).group(1) for slot_id in ("gfx-01", "gfx-02", "gfx-03")}
        self.assertEqual(tracks, {"gfx-01": "1", "gfx-02": "2", "gfx-03": "1"})

    def test_exit_on_cut_clamp_projected(self) -> None:
        slot = re.search(r'<div id="gfx-03"[^>]*>', self.index).group(0)
        self.assertIn('data-start="4"', slot)
        self.assertIn('data-duration="2"', slot)  # 9.0 clamped to the 6.0 seam
        entry = self.manifest["entries"][2]
        self.assertTrue(entry["exitClamped"])
        self.assertEqual(entry["outEnd"], 6.0)
        self.assertEqual(entry["authoredOutEnd"], 9.0)
        self.assertEqual(self.manifest["exitClampedCount"], 1)
        with open(os.path.join(
                self.out, "compositions/gfx-03-marker-highlight.html"),
                encoding="utf-8") as handle:
            instance = handle.read()
        root = re.search(
            r'<[^>]*data-composition-id="gfx-03-marker-highlight"[^>]*>',
            instance).group(0)
        self.assertIn('data-duration="2"', root)

    def test_storyboard_frames(self) -> None:
        with open(os.path.join(self.out, "STORYBOARD.md"),
                  encoding="utf-8") as handle:
            board = handle.read()
        self.assertIn("## Frame 1 — line-swap", board)
        self.assertIn("- src: compositions/gfx-01-line-swap.html", board)
        self.assertIn("- scene: thesis takeover", board)
        self.assertIn("## Frame 3 — marker-highlight", board)

    def test_manifest_round_trip_and_plan_binding(self) -> None:
        """New views bind both sidecars to the exact V2 normalizer identity."""
        self.assertEqual(unsynced_changes(self.out), [])
        self.assertEqual(self.manifest["entries"][1]["planId"], "callout-1")
        self.assertEqual(self.manifest["generator"], "studio-project-v2")
        self.assertEqual(self.manifest["compositionNormalizer"], "hf-ids-0.8.31")
        with open(os.path.join(self.out, FINGERPRINT_NAME),
                  encoding="utf-8") as handle:
            fingerprint = json.load(handle)
        self.assertEqual(fingerprint["generator"], "studio-project-v2")
        self.assertEqual(fingerprint["compositionNormalizer"], "hf-ids-0.8.31")
        self.assertEqual(fingerprint["base"]["path"], self.base)

    def test_force_gate_blocks_unsynced_edits(self) -> None:
        out = os.path.join(self.tmp, "studio-gate")
        generate_project(GenerateRequest(self.plan_path, self.base, out))
        with open(os.path.join(out, MANIFEST_NAME),
                  encoding="utf-8") as handle:
            first = json.load(handle)
        # clean regeneration is allowed without --force
        generate_project(GenerateRequest(self.plan_path, self.base, out))
        index_path = os.path.join(out, "index.html")
        with open(index_path, "a", encoding="utf-8") as handle:
            handle.write("<!-- studio edit -->\n")
        self.assertTrue(any("index.html" in c for c in unsynced_changes(out)))
        with self.assertRaises(StudioProjectError):
            generate_project(GenerateRequest(self.plan_path, self.base, out))
        code = main([self.plan_path, self.base, out])
        self.assertEqual(code, 2)
        result = generate_project(GenerateRequest(
            self.plan_path, self.base, out, force=True))
        self.assertEqual(result["status"], "generated")
        self.assertEqual(unsynced_changes(out), [])
        with open(os.path.join(out, MANIFEST_NAME),
                  encoding="utf-8") as handle:
            second = json.load(handle)
        self.assertEqual(first["files"], second["files"])  # deterministic


if __name__ == "__main__":
    unittest.main()
