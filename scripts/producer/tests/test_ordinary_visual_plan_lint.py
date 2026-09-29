"""Ordinary route compilation tests for allocated visual direction."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from _visual_plan_fixture import candidate, opportunity, visual_plan
from planner.ordinary_visual_plan_lint import MAX_JSON_BYTES, main
from planner.visual_plan_allocator import allocate_visual_plan
from planner.visual_plan_contract import invalidation_inputs
from planner.visual_plan_fields import canonical_hash


class OrdinaryVisualPlanLintTests(unittest.TestCase):
    """The gate binds selected candidates to exact executable plan rows."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _allocated(self, *opportunities: dict) -> tuple[Path, dict, bytes]:
        value = allocate_visual_plan(visual_plan(*opportunities))
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        path = self.root / "VISUAL-PLAN.json"
        path.write_bytes(data)
        return path, value, data

    @staticmethod
    def _application(visual: dict, data: bytes, plan: dict) -> dict:
        rows = []
        for index, selected in enumerate(visual["allocation"]["decisions"]):
            opportunity = visual["opportunities"][index]
            timing = opportunity["timing"]
            candidate_row = next(row for row in opportunity["candidates"]
                                 if row["id"] == selected["candidateId"])
            modality = selected["modality"]
            execution = {"presenter": "presenter-hold",
                         "omit": "intentional-omit"}.get(modality, "elements")
            lane = {"source-footage": "cutTrack", "presenter": "cutTrack",
                    "supplied-broll": "brollTrack", "external-media": "brollTrack",
                    "transition": "transitions"}.get(modality, "graphicsTrack")
            element = {"lane": lane, "index": index}
            elements = [] if modality == "omit" else [element]
            rows.append({
                "opportunityId": selected["opportunityId"],
                "candidateId": selected["candidateId"],
                "modality": modality,
                "execution": execution,
                "timing": timing,
                "elements": elements,
                "binding": OrdinaryVisualPlanLintTests._binding(
                    modality, candidate_row, plan, element, timing,
                    visual["project"]["fps"]["numerator"]
                    / visual["project"]["fps"]["denominator"]),
            })
        return {
            "schemaVersion": 1,
            "route": "ordinary",
            "visualPlan": {
                "byteHash": hashlib.sha256(data).hexdigest(),
                "visualPlanSha256": invalidation_inputs(visual)["visualPlanSha256"],
            },
            "decisions": rows,
        }

    @staticmethod
    def _binding(modality: str, candidate_row: dict, plan: dict,
                 element: dict, timing: dict, fps: float) -> dict:
        if modality == "omit":
            return {"kind": "omit"}
        row = plan[element["lane"]][element["index"]]
        if modality == "text":
            texts = [row["spec"]["text"]]
            content = {"visibleId": row["id"], "kind": row["kind"],
                       "visibleText": texts, "spec": row["spec"]}
            return {"kind": "text", "element": element,
                    "visibleId": row["id"], "visibleText": texts,
                    "contentSha256": canonical_hash(content)}
        if modality == "transition":
            return {"kind": "transition", "element": element,
                    "transitionId": row["id"], "mechanism": row["kind"],
                    "atFrame": round(row["outTime"] * fps),
                    "configurationSha256": canonical_hash(row)}
        source = candidate_row.get("source") or {}
        source_range = source.get("range")
        if modality in {"source-footage", "supplied-broll", "external-media"}:
            return {"kind": "media", "element": element,
                    "assetId": row.get("sourceId", row.get("assetId")),
                    "sourceSha256": source.get("sourceSha256", source.get("sha256")),
                    "sourceRange": source_range, "outputRange": timing,
                    "implementationSha256": canonical_hash(row)}
        if modality == "presenter":
            source_range = {"startFrame": round(row["start"] * fps),
                            "endFrameExclusive": round(row["end"] * fps)}
            return {"kind": "presenter", "element": element,
                    "sourceId": row["sourceId"], "sourceRange": source_range,
                    "outputRange": timing,
                    "implementationSha256": canonical_hash(row)}
        return {}

    def _fixture(self) -> tuple[Path, Path, dict, dict]:
        first = candidate("candidate:one")
        second = candidate("candidate:two", composition={
            "anatomy": "stacked-proof", "development": "proof-then-label"})
        visual_path, visual, data = self._allocated(
            opportunity("opp:one", 0, [first]),
            opportunity("opp:two", 30, [second]),
        )
        plan = {
            "cutTrack": [{"sourceId": "source", "start": 0, "end": 3}],
            "graphicsTrack": [
                {"id": "graphic-one", "kind": "kinetic-text", "outStart": 0,
                 "outEnd": 0.8, "spec": {"text": "First visible idea"}},
                {"id": "graphic-two", "kind": "kinetic-text", "outStart": 1,
                 "outEnd": 1.8, "spec": {"text": "Second visible idea"}},
            ],
        }
        plan["visualPlanApplication"] = self._application(visual, data, plan)
        plan_path = self.root / "edit_plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return plan_path, visual_path, plan, visual

    @staticmethod
    def _run(args: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(args)
        return code, json.loads(stdout.getvalue())

    def _rewrite(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_complete_application_passes_with_controller_binding(self) -> None:
        plan_path, visual_path, plan, _ = self._fixture()
        binding = plan["visualPlanApplication"]["visualPlan"]
        code, verdict = self._run([
            str(plan_path), str(visual_path),
            "--expected-byte-hash", binding["byteHash"],
            "--expected-visual-plan-sha256", binding["visualPlanSha256"],
        ])
        self.assertEqual(code, 0)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["metrics"]["applicationDecisions"], 2)

    def test_missing_mismatched_and_nonselected_receipts_fail(self) -> None:
        plan_path, visual_path, plan, _ = self._fixture()
        cases = []
        missing = copy.deepcopy(plan)
        del missing["visualPlanApplication"]
        cases.append((missing, "visualPlanApplication is required"))
        nonselected = copy.deepcopy(plan)
        nonselected["visualPlanApplication"]["decisions"][0]["candidateId"] = "candidate:other"
        cases.append((nonselected, "candidateId does not match selected allocation"))
        stale = copy.deepcopy(plan)
        stale["visualPlanApplication"]["visualPlan"]["byteHash"] = "0" * 64
        cases.append((stale, "byteHash does not bind"))
        for value, message in cases:
            with self.subTest(message=message):
                self._rewrite(plan_path, value)
                code, verdict = self._run([str(plan_path), str(visual_path)])
                self.assertEqual(code, 1)
                self.assertIn(message, " ".join(verdict["errors"]))

    def test_duplicate_and_timing_inconsistent_element_refs_fail(self) -> None:
        plan_path, visual_path, plan, _ = self._fixture()
        duplicate = copy.deepcopy(plan)
        duplicate["visualPlanApplication"]["decisions"][1]["elements"][0]["index"] = 0
        self._rewrite(plan_path, duplicate)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("duplicates an element", " ".join(verdict["errors"]))
        timing = copy.deepcopy(plan)
        timing["graphicsTrack"][0]["outStart"] = 0.25
        self._rewrite(plan_path, timing)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("timing does not realize", " ".join(verdict["errors"]))

    def test_controller_authority_cannot_drift(self) -> None:
        plan_path, visual_path, plan, visual = self._fixture()
        project = json.dumps(visual["project"], sort_keys=True)
        catalog = canonical_hash(visual["catalogPin"])
        controller = canonical_hash({key: visual[key] for key in (
            "transcriptAuthority", "mediaAuthority", "relatedUsageAuthority",
            "relatedUsage")})
        code, verdict = self._run([str(plan_path), str(visual_path),
                                   "--expected-project-json", project,
                                   "--expected-catalog-pin-sha256", catalog,
                                   "--expected-controller-authority-sha256", controller])
        self.assertEqual(code, 0, verdict)
        stale = {**visual["project"], "intentSha256": "0" * 64}
        code, verdict = self._run([str(plan_path), str(visual_path),
                                   "--expected-project-json", json.dumps(stale)])
        self.assertEqual(code, 1)
        self.assertIn("project authority differs", " ".join(verdict["errors"]))
        code, verdict = self._run([str(plan_path), str(visual_path),
                                   "--expected-controller-authority-sha256", "0" * 64])
        self.assertEqual(code, 1)
        self.assertIn("related-usage authority differs", " ".join(verdict["errors"]))

    def test_source_modality_requires_exact_cut_ownership_and_range(self) -> None:
        source = candidate("candidate:source", "source-footage", source={
            "range": {"startFrame": 0, "endFrameExclusive": 24},
        })
        source["evidence"][0]["kind"] = "source-range"
        visual_path, visual, data = self._allocated(
            opportunity("opp:source", 0, [source]))
        plan = {"cutTrack": [{"sourceId": "record:candidate:source",
                              "start": 0, "end": 0.8}]}
        application = self._application(visual, data, plan)
        application["decisions"][0]["elements"] = [{"lane": "cutTrack", "index": 0}]
        application["decisions"][0]["binding"] = self._binding(
            "source-footage", source, plan, {"lane": "cutTrack", "index": 0},
            visual["opportunities"][0]["timing"], 30)
        plan["visualPlanApplication"] = application
        plan_path = self.root / "source-plan.json"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 0, verdict)
        plan["cutTrack"][0]["sourceId"] = "different-source"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("media source identity", " ".join(verdict["errors"]))

    def test_text_binding_rejects_content_and_generic_id_substitution(self) -> None:
        plan_path, visual_path, plan, _ = self._fixture()
        plan["graphicsTrack"][0]["spec"]["text"] = "Substituted visible idea"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("execution binding differs", " ".join(verdict["errors"]))
        plan["visualPlanApplication"]["decisions"][0]["binding"]["visibleId"] = "graphic"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("execution binding differs", " ".join(verdict["errors"]))

    def test_transition_binding_rejects_mechanism_and_exact_time_drift(self) -> None:
        transition = candidate("candidate:transition", "transition")
        side = {"motion": "settled", "composition": "presenter", "color": "ink",
                "audio": "continuous", "narrative": "one idea"}
        seam = {"left": {"sceneId": "scene:left", **side},
                "right": {"sceneId": "scene:right", **side},
                "relationship": "continuous thought"}
        visual_path, visual, data = self._allocated(
            opportunity("opp:transition", 0, [transition], kind="seam",
                        seamContext=seam))
        plan = {"transitions": [{"id": "transition-one", "kind": "whip-cut",
                                  "outTime": 0.4, "duration": 0.2}]}
        plan["visualPlanApplication"] = self._application(visual, data, plan)
        plan_path = self.root / "transition-plan.json"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 0, verdict)
        for key, value in (("kind", "generic"), ("outTime", 0.5)):
            changed = copy.deepcopy(plan)
            changed["transitions"][0][key] = value
            self._rewrite(plan_path, changed)
            code, verdict = self._run([str(plan_path), str(visual_path)])
            self.assertEqual(code, 1)
            self.assertIn("execution binding differs", " ".join(verdict["errors"]))

    def test_supplied_media_requires_admitted_broll_range_and_hash(self) -> None:
        supplied = candidate("candidate:supplied", "supplied-broll", source={
            "range": {"startFrame": 60, "endFrameExclusive": 84},
        })
        visual_path, visual, data = self._allocated(
            opportunity("opp:supplied", 0, [supplied]))
        plan = {"brollTrack": [{"assetId": "record:candidate:supplied",
                                 "assetStart": 2, "outStart": 0, "outEnd": 0.8}]}
        plan["visualPlanApplication"] = self._application(visual, data, plan)
        plan_path = self.root / "supplied-plan.json"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 0, verdict)
        plan["visualPlanApplication"]["decisions"][0]["binding"]["sourceSha256"] = "0" * 64
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("execution binding differs", " ".join(verdict["errors"]))

    def test_style_application_anatomy_and_development_cannot_drift(self) -> None:
        plan_path, visual_path, plan, _ = self._fixture()
        plan["styleApplication"] = {
            "choices": [{
                "graphicId": "graphic-one", "anatomy": "wrong-card",
                "development": "label-then-proof",
            }],
            "supplementalChoices": [{
                "graphicId": "graphic-two", "anatomy": "stacked-proof",
                "development": "proof-then-label",
            }],
        }
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("styleApplication anatomy differs", " ".join(verdict["errors"]))
        plan["styleApplication"]["choices"][0]["anatomy"] = "split-card"
        self._rewrite(plan_path, plan)
        code, verdict = self._run([str(plan_path), str(visual_path)])
        self.assertEqual(code, 0, verdict)

    def test_presenter_and_omit_are_explicit_zero_element_decisions(self) -> None:
        for modality, execution in (("presenter", "presenter-hold"),
                                    ("omit", "intentional-omit")):
            with self.subTest(modality=modality):
                visual_path, visual, data = self._allocated(
                    opportunity(f"opp:{modality}", 0,
                                [candidate(f"candidate:{modality}", modality)]))
                selected = visual["allocation"]["decisions"][0]
                plan = {"cutTrack": [{"sourceId": "presenter-source",
                                       "start": 0, "end": 0.8}]}
                if modality == "omit":
                    plan["graphicsTrack"] = []
                application = self._application(visual, data, plan)
                if modality == "presenter":
                    application["decisions"][0]["elements"] = [
                        {"lane": "cutTrack", "index": 0}]
                    application["decisions"][0]["binding"] = self._binding(
                        modality, visual["opportunities"][0]["candidates"][0], plan,
                        {"lane": "cutTrack", "index": 0},
                        visual["opportunities"][0]["timing"], 30)
                plan_path = self.root / f"edit-plan-{modality}.json"
                plan["visualPlanApplication"] = application
                self._rewrite(plan_path, plan)
                code, verdict = self._run([str(plan_path), str(visual_path)])
                self.assertEqual(code, 0, verdict)

    def test_reads_are_bounded_before_json_parse(self) -> None:
        plan_path, visual_path, _, _ = self._fixture()
        oversized = self.root / "oversized.json"
        with oversized.open("wb") as handle:
            handle.truncate(MAX_JSON_BYTES + 1)
        code, verdict = self._run([str(oversized), str(visual_path)])
        self.assertEqual(code, 1)
        self.assertIn("bounded read size", " ".join(verdict["errors"]))
        code, verdict = self._run([
            str(plan_path), str(visual_path), "--expected-byte-hash", "bad"])
        self.assertEqual(code, 1)
        self.assertIn("controller expected hashes", " ".join(verdict["errors"]))


if __name__ == "__main__":
    unittest.main()
