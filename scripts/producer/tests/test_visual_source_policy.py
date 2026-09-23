"""Production boundaries reject retired designs and bind explicit source choices."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from graphics import visual_source_policy as policy
from graphics.visual_source_receipt import carry_scene_source_choice, subject_hash, validate_visual_sources
from graphics.visual_source_project import native_short_subject
from graphics.template_contract import template_catalog
from graphics.catalog_discovery import load_catalog
from graphics.graphics_render import comp_path


class SourcePolicyTests(unittest.TestCase):
    """Real repository inventory plus synthetic request evidence; no rendering."""

    def test_scoped_scene_revision_preserves_source_choice_but_changes_subject(self) -> None:
        from scene_fixtures import fire_sparkles_scene
        from graphics.scene_contract import validate_scene
        before = fire_sparkles_scene('a' * 64)
        after = copy.deepcopy(before)
        after['version'] += 1
        after['composition']['variables']['rightTitle'] = 'Revised TEST copy'
        after['elements'][2]['values']['rightTitle'] = 'Revised TEST copy'
        original = copy.deepcopy(before)
        carry_scene_source_choice(before, after, 'variable')
        self.assertEqual(validate_scene(after), after)
        self.assertEqual(before, original)
        self.assertEqual(before['visualSources']['decisions'], after['visualSources']['decisions'])
        self.assertNotEqual(before['visualSources']['subjectSha256'], after['visualSources']['subjectSha256'])

    def test_scoped_scene_revision_cannot_rebind_design_or_stale_source(self) -> None:
        from scene_fixtures import fire_sparkles_scene
        before = fire_sparkles_scene('a' * 64)
        for mutate in (lambda x: x['composition'].update(bundleHash='b' * 64),
                       lambda x: x['elements'][0].update(role='new-design'),
                       lambda x: x['visualSources']['decisions'][0].update(scope='Replace the design')):
            after = copy.deepcopy(before)
            after['version'] += 1
            mutate(after)
            with self.subTest(change=after), self.assertRaisesRegex(ValueError, 'source selection or scene structure'):
                carry_scene_source_choice(before, after, 'variable')
        before['visualSources']['subjectSha256'] = '0' * 64
        after = copy.deepcopy(before)
        after['version'] += 1
        with self.assertRaisesRegex(ValueError, 'authored design changed'):
            carry_scene_source_choice(before, after, 'variable')

    def test_only_upstream_ports_remain(self) -> None:
        expected = policy.integrated_kinds()
        self.assertEqual(set(template_catalog()), expected)
        self.assertEqual(len(expected), 7)
        for kind in policy.policy()["retired"]:
            self.assertFalse((policy.ROOT / f"templates/motion/compositions/{kind}.html").exists())
            with self.assertRaises(ValueError):
                comp_path(kind)
        self.assertEqual(len(load_catalog().records), 372)

    def test_raw_plan_rejects_every_legacy_lane(self) -> None:
        for plan in ({"graphicsTrack": [{"kind": "section-marker"}]},
                     {"transitions": [{"kind": "white-flash"}]},
                     {"titleCards": [{"text": "old"}]},
                     {"target": {"visualProfile": "retired-profile"}},
                     {"target": {"style": "retired-style"}}):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                policy.require_plan_sources(plan)
        policy.require_plan_sources({"target": {"graphicsStyle": "catalog-first"},
                                     "graphicsTrack": [{"kind": "hw-callout-circle"}]})

    def test_retired_experimental_paths_fail_before_execution(self) -> None:
        from headless.prebound_clips import _plan_row_values
        from graphics.pip_takeover import run_segment
        with self.assertRaisesRegex(ValueError, "retired"):
            _plan_row_values({"kind": "section-marker"})
        with self.assertRaisesRegex(ValueError, "retired"):
            run_segment(None)

    def test_present_invalid_styles_cannot_silently_select_default(self) -> None:
        for field in ("style", "visualProfile", "graphicsStyle"):
            for value in ("", None, False, {}, [], "wallpaper"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "catalog-first"):
                    policy.require_plan_sources({"target": {field: value}})
        for target in ({}, {"graphicsStyle": "catalog-first"}, None):
            policy.require_plan_sources({"target": target})

    def test_changed_port_cannot_claim_catalog_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "source changed"):
            policy.require_integrated("line-swap", "<html>replacement</html>")

    def test_source_receipts_are_exact_and_current(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder).resolve() / "request.json"
            request.write_text(json.dumps({"selectedReferences": []}))
            subject = {"files": {"index.html": "synthetic authored hash"}}
            port = policy.policy()["integrated"]["count-up"]
            item = {"id": "count-up", "sourceSha256": port["upstreamSha256"]}
            receipt = {"schemaVersion": 1, "policyVersion": policy.policy()["policyVersion"],
                       "subjectSha256": subject_hash(subject),
                       "request": {"path": str(request), "sha256": hashlib.sha256(request.read_bytes()).hexdigest()},
                       "decisions": [{"route": "catalog", "targets": ["index.html"],
                                      "reason": "The counter communicates the actual metric.", "catalog": [item],
                                      "configuration": "Configure the recorded metric and its readable timing."}]}
            result = validate_visual_sources(receipt, subject, ["index.html"])
            self.assertTrue(result["sourceEvidenceChecked"])
            self.assertFalse(result["visualQualityApproved"])
            for change in (lambda r: r.update(subjectSha256="0" * 64),
                           lambda r: r["decisions"][0].update(targets=["invented"]),
                           lambda r: r["decisions"][0]["catalog"][0].update(sourceSha256="0" * 64),
                           lambda r: r.update(decisions=[])):
                bad = copy.deepcopy(receipt)
                change(bad)
                with self.assertRaises(ValueError):
                    validate_visual_sources(bad, subject, ["index.html"])
            custom = copy.deepcopy(receipt)
            custom["decisions"] = [{"route": "custom", "targets": ["index.html"],
                "reason": "The source needs a measured basketball court layout.",
                "gapType": "missing-capability", "query": "basketball court movement diagram",
                "gap": "The inspected counter cannot express player positions on a court.",
                "scope": "Build only the source-specific court geometry and player paths.",
                "inspected": [{**item, "limitation": "A numeric counter cannot depict spatial player positions."}]}]
            validate_visual_sources(custom, subject, ["index.html"])
            custom["decisions"][0]["gapType"] = "setup-unavailable"
            with self.assertRaisesRegex(ValueError, "capability or quality"):
                validate_visual_sources(custom, subject, ["index.html"])
            reference = copy.deepcopy(receipt)
            reference["decisions"] = [{"route": "reference", "targets": ["index.html"],
                "reason": "Match the selected coaching reference treatment.", "reference": receipt["request"],
                "adaptation": "Adapt the selected motion relationship to this footage."}]
            with self.assertRaisesRegex(ValueError, "not explicitly selected"):
                validate_visual_sources(reference, subject, ["index.html"])

    def test_explicit_current_job_reference_is_accepted_and_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ref = Path(directory).resolve() / "reference.json"
            ref.write_text('{"scope":"synthetic reference evidence"}')
            ref_pin = {"path": str(ref), "sha256": hashlib.sha256(ref.read_bytes()).hexdigest()}
            request = ref.with_name("request.json")
            request.write_text(json.dumps({"selectedReferences": [ref_pin]}))
            subject = {"files": {"index.html": "synthetic design identity"}}
            receipt = {"schemaVersion": 1, "policyVersion": policy.policy()["policyVersion"],
                "subjectSha256": subject_hash(subject),
                "request": {"path": str(request), "sha256": hashlib.sha256(request.read_bytes()).hexdigest()},
                "decisions": [{"route": "reference", "targets": ["index.html"], "reference": ref_pin,
                    "reason": "The user selected this specific coaching reference for this job.",
                    "adaptation": "Keep its observed annotation sequence using the new footage."}]}
            self.assertTrue(validate_visual_sources(receipt, subject, ["index.html"])["sourceEvidenceChecked"])
            ref.write_text("changed reference")
            with self.assertRaisesRegex(ValueError, "source evidence changed"):
                validate_visual_sources(receipt, subject, ["index.html"])

    def test_short_subject_covers_non_html_and_catalog_lanes(self) -> None:
        subject, targets = native_short_subject({"canvas": {"text": [{"id": "hook"}],
            "shapes": [], "captionViews": [{}], "titleCard": {}},
            "extension": {"markup": "<div/>"}, "catalogFiles": [{"file": "compositions/chart.html"}]})
        self.assertEqual(targets, ["caption-presentation", "compositions/chart.html", "hook", "scene-extension"])
        self.assertIn("catalogFiles", subject)


if __name__ == "__main__":
    unittest.main()
