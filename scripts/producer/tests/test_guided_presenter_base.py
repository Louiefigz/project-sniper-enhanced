"""Pure/stub base-entry faults; no native decode, admission or source-color proof."""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _guided_presenter_observation_fixture import ObservationFixture
from assemble_arguments import load_documents
from audio.assemble_picture_reuse import picture_reuse_supported
from graphics.owned_execution import require_held_assembly
from graphics.presenter_layout_contract import declaration_payload
from guided_opening_inputs import OpeningInputs
from guided_opening_prepare import prepare_full_program
from guided_presenter_base import (PresenterBaseContext, SOURCE_COLOR_UNRESOLVED,
    require_presenter_base, require_presenter_preparation)
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from render import RenderCtx, _write_base_artifacts, main as render_main, render


class PresenterBaseTests(unittest.TestCase):
    """Live TEST observation control flow never qualifies original source color."""

    def setUp(self) -> None:
        """Create actual small files and stub only the selected asset probe output."""
        self.fixture = ObservationFixture()
        self.addCleanup(self.fixture.close)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            observed = observe_presenter_asset(self.fixture.selected, self.fixture.source,
                                                "30000/1001", self.fixture.runtime)
        self.owner = OwnedPresenterExecution((self.fixture.selected,), (observed,),
                                            "30000/1001", self.fixture.runtime)
        selected = self.fixture.selected
        self.plan = {"target": {"mode": "longform", "width": 64, "height": 36},
            "presenterLayouts": [{"operationIndex": selected.operation_index,
                "startFrame": selected.geometry.timing.start_frame,
                "endFrameExclusive": selected.geometry.timing.end_frame_exclusive,
                "layout": declaration_payload(selected.geometry)}]}
        self.manifest = {"sources": [{"id": "TEST-talking-source", "path": self.fixture.source.path}]}
        self.refs = {name: {"path": str(self.fixture.root / (name + ".json")), "sha256": "b" * 64}
                     for name in ("candidatePlan", "manifest")}
        self.inputs = OpeningInputs(self.fixture.root / "TEST-input.json", "c" * 64,
            {"documents": self.refs}, {"candidatePlan": self.plan, "manifest": self.manifest,
                "authority": {"frameRate": "30000/1001", "totalFrames": 24,
                    "target": {"width": 64, "height": 36}}})
        self.context = PresenterBaseContext(self.inputs, self.owner)

    def ctx(self) -> RenderCtx:
        """Prepare arguments only; no output directory is created."""
        manifest = {**copy.deepcopy(self.manifest), "_path": self.refs["manifest"]["path"]}
        return RenderCtx(copy.deepcopy(self.plan), manifest, str(self.fixture.root / "not-created"),
            str(self.fixture.root / "not-created-work"), skip_graphics=True, audio_clock_policy="source-float-v2",
            plan_path=self.refs["candidatePlan"]["path"], presenter_base=self.context)

    def test_any_unowned_property_presence_stops_before_audio_admission(self) -> None:
        """Empty/null/false layouts must not be silently ignored by direct render."""
        for value in (None, [], False, {"enabled": True}):
            ctx = self.ctx()
            ctx.plan["presenterLayouts"], ctx.presenter_base = value, None
            with self.subTest(value=value), patch("render.admit_audio") as admit:
                self.assertRaisesRegex(RuntimeError, "actual live preparation context", render, ctx)
                admit.assert_not_called()

    def test_live_selected_owner_cannot_replace_original_source_color(self) -> None:
        """The selected asset really passed the stub observer; that is a different source."""
        ctx = self.ctx()
        prior_bus = object()
        ctx.source_audio_bus = prior_bus
        with patch("render.admit_audio") as admit, patch("render.gate") as gate:
            with self.assertRaisesRegex(RuntimeError, SOURCE_COLOR_UNRESOLVED):
                render(ctx)
        self.assertIs(ctx.source_audio_bus, prior_bus)
        admit.assert_not_called()
        gate.assert_not_called()
        self.assertFalse(Path(ctx.out_dir).exists())

    def test_legacy_entry_still_reaches_unchanged_admission(self) -> None:
        """The absent-property branch is a no-op, including ordinary state reset."""
        ctx = self.ctx()
        del ctx.plan["presenterLayouts"]
        ctx.presenter_base, ctx.source_audio_bus = None, object()
        with patch("render.admit_audio", side_effect=RuntimeError("TEST old admission reached")) as admit:
            with self.assertRaisesRegex(RuntimeError, "old admission reached"):
                render(ctx)
        self.assertIsNone(ctx.source_audio_bus)
        admit.assert_called_once_with(ctx.plan, ctx.manifest, (ctx.audio_clock_policy, ctx.resume))

    def test_only_fresh_owned_source_float_base_mode_is_eligible(self) -> None:
        """Neither monolithic delivery nor coerced flags nor resume can enter."""
        for key, value in (("skip_graphics", False), ("skip_graphics", 1), ("resume", True),
                           ("resume", 0), ("audio_clock_policy", "legacy-v1")):
            ctx = self.ctx()
            setattr(ctx, key, value)
            with self.subTest(key=key, value=value), self.assertRaisesRegex(RuntimeError, "fresh owned"):
                require_presenter_base(ctx)

    def test_whole_candidate_manifest_and_plan_path_remain_bound(self) -> None:
        """A matching presenter track alone cannot authorize a different base plan."""
        mutations = (lambda ctx: ctx.plan.update(music={"enabled": True}),
            lambda ctx: ctx.manifest.update(sources=[]),
            lambda ctx: setattr(ctx, "plan_path", "/TEST/different-candidate.json"))
        for mutate in mutations:
            ctx = self.ctx()
            mutate(ctx)
            with self.subTest(mutation=mutate), self.assertRaisesRegex(RuntimeError, "exact held candidate or manifest"):
                require_presenter_base(ctx)

    def test_original_input_clock_and_owner_changes_fail_before_color(self) -> None:
        """Input and runtime faults remain explicit, not a renewable color check."""
        ctx = self.ctx()
        self.inputs.documents["candidatePlan"]["music"] = None
        with self.assertRaisesRegex(RuntimeError, "original input changed"):
            require_presenter_base(ctx)
        del self.inputs.documents["candidatePlan"]["music"]
        self.fixture.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            require_presenter_base(ctx)

    def test_serialized_context_and_replacement_inputs_cannot_own_preparation(self) -> None:
        """Even equal-value inputs must be the actual held execution inputs."""
        with self.assertRaisesRegex(RuntimeError, "actual live preparation context"):
            require_presenter_preparation(self.inputs, {"sourceColor": "bt709"})
        with self.assertRaisesRegex(RuntimeError, "exact original opening inputs"):
            require_presenter_preparation(replace(self.inputs), self.context)

    def test_color_labels_and_status_flags_do_not_unlock_the_live_branch(self) -> None:
        """Self-asserted source metadata is not an actual source-before-encode observation."""
        self.manifest["sources"][0].update(color_space="bt709", color_transfer="bt709", color_range="tv")
        self.inputs.value["sourceColorQualified"] = True
        self.context = PresenterBaseContext(self.inputs, self.owner)
        with self.assertRaisesRegex(RuntimeError, SOURCE_COLOR_UNRESOLVED):
            require_presenter_base(self.ctx())

    def test_preparation_refuses_before_dependency_reads_or_directory_creation(self) -> None:
        """The optional fourth argument does not start a partial base attempt."""
        root = self.fixture.root / "unstarted-preparation"
        with patch("guided_opening_prepare._validate_preparation") as validate, \
                patch("guided_opening_prepare.caption_input_dependencies") as captions:
            with self.assertRaisesRegex(RuntimeError, SOURCE_COLOR_UNRESOLVED):
                prepare_full_program(self.inputs, root, lambda: None, self.context)
        validate.assert_not_called()
        captions.assert_not_called()
        self.assertFalse(root.exists())

    def test_direct_base_publication_rechecks_before_any_sidecar_write(self) -> None:
        """Calling the bookkeeping helper cannot mint presenter base provenance."""
        ctx = self.ctx()
        with patch("render.fingerprint_record") as fingerprint:
            with self.assertRaisesRegex(RuntimeError, SOURCE_COLOR_UNRESOLVED):
                _write_base_artifacts(ctx, SimpleNamespace(output_duration=1), {})
        fingerprint.assert_not_called()
        self.assertFalse(Path(ctx.out_dir).exists())

    def test_cli_refuses_before_source_verification_and_auto_base_dispatch(self) -> None:
        """Use the real CLI loader boundary, not a parser-only predicate."""
        path = self.fixture.root / "cli-plan.json"
        for value in (None, [], False, self.plan["presenterLayouts"]):
            path.write_text(json.dumps({"presenterLayouts": value}), encoding="utf-8")
            with self.subTest(value=value), patch("assemble.verify_execution_media_authority") as verify:
                self.assertRaisesRegex(RuntimeError, "unowned render or base",
                                       load_documents, SimpleNamespace(plan_path=str(path)))
                verify.assert_not_called()

    def test_presenter_never_uses_unowned_assembly_or_picture_reuse(self) -> None:
        """Protect both reuse dispatch and the existing actual assembly boundary."""
        for value in (None, [], False, self.plan["presenterLayouts"]):
            plan = {"presenterLayouts": value}
            with self.subTest(value=value):
                self.assertFalse(picture_reuse_supported(plan))
                self.assertRaisesRegex(RuntimeError, "unowned assembly", require_held_assembly,
                                       SimpleNamespace(plan=plan))
        self.assertTrue(picture_reuse_supported({}))

    def test_render_cli_refuses_before_manifest_read_or_output_setup(self) -> None:
        """The actual parser/entry path refuses even with the old migration flag."""
        path, output = self.fixture.root / "render-plan.json", self.fixture.root / "unstarted-cli"
        path.write_text(json.dumps({"presenterLayouts": None}), encoding="utf-8")
        argv = ["render.py", str(path), str(self.fixture.root / "absent-manifest.json"), str(output),
                "--skip-graphics", "--allow-legacy-unadmitted"]
        with patch("sys.argv", argv), patch("render.emit") as emit, \
                patch("render.verify_execution_media_authority") as verify:
            with self.assertRaises(SystemExit) as stopped:
                render_main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("unowned render or base", emit.call_args.kwargs["error"])
        verify.assert_not_called()
        self.assertFalse(output.exists())

    def test_absent_layout_cannot_borrow_a_live_presenter_context(self) -> None:
        """The guard rejects mismatched ownership instead of silently discarding it."""
        ctx = self.ctx()
        del ctx.plan["presenterLayouts"]
        with self.assertRaisesRegex(RuntimeError, "no requested presenter"):
            require_presenter_base(ctx)

    def _stub_legacy_chain(self) -> None:
        """Replace all renderer work; only guard ordering and state transitions run."""
        tmap = SimpleNamespace(segments=[], output_duration=1)
        values = {"gate": None, "compile_stage": tmap, "cut_stage": "TEST-cut", "channels_stage": "TEST-base",
            "baseline_stage": "TEST-base", "reframe_stage": "TEST-base", "recompose_stage": None,
            "punch_stage": "TEST-base", "broll_stage": "TEST-base", "overlays_stage": "TEST-base",
            "captions_stage": None, "longform_sidecar_stage": None, "_suppress_legacy_base_captions": None,
            "enhance_stage": "TEST-base", "transitions_stage": "TEST-base", "gain_stage": "TEST-base",
            "master_stage": {"out": "TEST-final"}, "admit_audio": None, "emit": None}
        for name, value in values.items():
            self.enterContext(patch("render." + name, return_value=value))
        self.enterContext(patch("palmier_visual_bootstrap_authority.seal_palmier_visual_bootstrap",
            return_value={"receiptHash": "TEST-not-authority", "bootstrapArtifact": {"videoFrames": 24}}))

    def test_late_presenter_injection_stops_before_delivery_or_base_publication(self) -> None:
        """A legacy entry cannot acquire an ignored field during an intervening stage."""
        ctx = self.ctx()
        del ctx.plan["presenterLayouts"]
        ctx.presenter_base = None
        self._stub_legacy_chain()
        with patch("render._burn_explicit_caption_shards", side_effect=lambda *args: ctx.plan.update(presenterLayouts=[])), \
                patch("render.seal_render_delivery") as delivery, patch("render._write_base_artifacts") as base:
            with self.assertRaisesRegex(RuntimeError, "actual live preparation context"):
                render(ctx)
        delivery.assert_not_called()
        base.assert_not_called()

    def test_context_constructor_rejects_duck_typed_success_records(self) -> None:
        """A fake callback or deserialized observation never becomes a live owner."""
        with self.assertRaisesRegex(RuntimeError, "actual inputs and live observation owner"):
            PresenterBaseContext(self.inputs, SimpleNamespace(status="verified"))


if __name__ == "__main__":
    unittest.main()
