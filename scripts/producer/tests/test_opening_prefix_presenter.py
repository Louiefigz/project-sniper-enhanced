"""Pure presenter-prefix graph/binding faults; no renderer or creator authority."""
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from _opening_prefix_presenter_fixture import PrefixPresenterFixture
from graphics.presenter_layout_geometry import compile_presenter_geometry
from opening_prefix_composition import _command, compose_verified_prefix, PrefixCompositionJob
from opening_prefix_contract import PrefixDeadline, PrefixOracleError, canonical_hash, validate_request
from opening_prefix_graphs import (assert_presenter_graph_proof, freeze_request, graph_hash,
                                   graph_layer_policy, graph_projection, proof_header)
from opening_prefix_oracle import _graphic_workload, _raw_command, verify_compositor_prefix
from opening_prefix_presenter import (presenter_graph_payload, presenter_observation_records,
                                      validate_presenter_base)
from test_presenter_layout_graph import declaration
from test_guided_caption_layers import page
from guided_caption_layers import caption_prefix_request


class PresenterPrefixTests(unittest.TestCase):
    """Exact new proof domain and all held metadata, independent of pixel claims."""

    def setUp(self) -> None:
        """Use fresh tiny files and explicitly mocked decoder records."""
        self.fixture = PrefixPresenterFixture()
        self.addCleanup(self.fixture.close)
        self.request, self.runtime = self.fixture.request, self.fixture.runtime

    def test_crossing_opening_keeps_whole_original_geometry_and_future_full_window(self) -> None:
        """The review end never changes an operation's exit or source offset."""
        validate_request(self.request, self.runtime)
        payload = presenter_graph_payload(self.request.presenter.opening)
        self.assertEqual(payload["windows"][0]["frameRange"], [2, 18])
        self.assertEqual(payload["windows"][0]["declaration"]["assetStart"], {"numerator": 0, "denominator": 1})
        self.assertEqual(payload["canvas"]["total_frames"], 48)
        self.assertEqual(len(self.request.presenter.full.windows), 2)
        frozen = freeze_request(self.request)
        self.assertIs(frozen.presenter.observations[0], self.fixture.observed)
        self.assertIsNot(frozen.presenter.full, self.request.presenter.full)

    def test_changed_or_omitted_opening_windows_fail_before_any_process(self) -> None:
        """A superficially matching prefix cannot launder shortened or missing intent."""
        full, opening = self.request.presenter.full, self.request.presenter.opening
        clipped = replace(opening.windows[0], geometry=compile_presenter_geometry(declaration(), full.canvas, (2, 12)))
        variants = (None, full, replace(opening, windows=(clipped,)), replace(opening, frame_rate="30"))
        for value in variants:
            request = replace(self.request, presenter=replace(self.request.presenter, opening=value))
            with patch("opening_prefix_oracle._run") as run, self.assertRaises(PrefixOracleError):
                verify_compositor_prefix(request, self.runtime)
            run.assert_not_called()

    def test_all_future_graph_has_no_opening_spec_and_retains_full_hash(self) -> None:
        """Empty opening selection is None, not an invalid empty full graph."""
        full = replace(self.request.presenter.full, windows=self.request.presenter.full.windows[1:])
        request = replace(self.request, presenter=replace(self.request.presenter, full=full, opening=None))
        validate_request(request, self.runtime)
        self.assertIsNone(graph_projection(request, "opening")["presenter"])
        self.assertEqual(graph_projection(request, "opening")["presenterInputs"], [])
        self.assertNotEqual(graph_hash(request, "full"), graph_hash(self.request, "full"))
        command, _digest = _raw_command(request, self.runtime, ("review", (0, 12)))
        self.assertNotIn(self.fixture.observed.source.path, command)

    def test_inventory_rejects_unheld_extra_duplicate_or_base_alias(self) -> None:
        """The new input role cannot bypass the original complete file inventory."""
        assets = self.request.presenter.assets
        for changed in ((), assets * 2, (*assets, self.request.base)):
            with self.assertRaises(PrefixOracleError):
                validate_request(replace(self.request, presenter=replace(self.request.presenter, assets=changed)), self.runtime)
        with self.assertRaises(PrefixOracleError):
            validate_request(replace(self.request, base=assets[0]), self.runtime)

    def test_new_domain_binds_future_geometry_and_rejects_legacy_proof(self) -> None:
        """Changing later geometry is detectable although no prefix pixel can show it."""
        full = self.request.presenter.full
        payload = declaration()
        payload["mask"]["radiusPx"] = 3
        future = replace(full.windows[1], geometry=compile_presenter_geometry(payload, full.canvas, (30, 42)))
        changed = replace(self.request, presenter=replace(self.request.presenter, full=replace(full, windows=(full.windows[0], future))))
        self.assertNotEqual(graph_hash(changed, "full"), graph_hash(self.request, "full"))
        self.assertEqual(graph_hash(changed, "opening"), graph_hash(self.request, "opening"))
        proof = {**proof_header(self.request), **graph_layer_policy(self.request), "status": "verified",
                 "fullGraphHash": graph_hash(self.request, "full"), "openingGraphHash": graph_hash(self.request, "opening")}
        assert_presenter_graph_proof(self.request, proof)
        with self.assertRaisesRegex(PrefixOracleError, "schema2"):
            assert_presenter_graph_proof(self.request, {**proof, "schemaVersion": 1, "kind": "compositor-prefix-oracle"})
        legacy = replace(self.request, presenter=None)
        self.assertEqual(graph_hash(legacy, "full"), canonical_hash([]))
        self.assertEqual(graph_layer_policy(legacy), {})

    def test_combined_surface_cap_counts_presenter_occurrences_in_addition_to_clips(self) -> None:
        """Independent presenter and graphic caps cannot each consume the full limit."""
        spec = self.request.presenter.full
        window = replace(spec.windows[0], asset=replace(spec.windows[0].asset, width=1920, height=1080))
        presenter = replace(self.request.presenter, full=replace(spec, windows=(window,)), opening=replace(spec, windows=(window,)))
        clips = tuple({"path": "/TEST/graphic"} for _ in range(32))
        request = replace(self.request, full_clips=clips, presenter=presenter)
        metadata = {"/TEST/graphic": {"width": 1920, "height": 1080}}
        _graphic_workload(replace(request, presenter=None), metadata)
        with self.assertRaisesRegex(PrefixOracleError, "aggregate native input"):
            _graphic_workload(request, metadata)

    def test_held_observations_bind_real_hash_stat_tool_graph_and_light_deadline(self) -> None:
        """Revalidation parses retained fake evidence but never invokes a second decode."""
        identities, deadline = self.fixture.identities(), PrefixDeadline(5)
        with patch("guided_presenter_observation.run_text", side_effect=AssertionError("duplicate observation")):
            record = presenter_observation_records(self.request, self.runtime, identities, deadline)
        self.assertEqual(len(record["presenterObservations"]), 1)
        self.assertGreater(self.fixture.guard_calls, 0)
        observed = self.fixture.observed
        wrong = replace(observed, source=replace(observed.source, sha256="0" * 64))
        request = replace(self.request, presenter=replace(self.request.presenter, observations=(wrong,)))
        with self.assertRaisesRegex(PrefixOracleError, "independently verified"):
            presenter_observation_records(request, self.runtime, identities, deadline)
        with patch.object(deadline, "remaining", side_effect=RuntimeError("TEST expired")):
            with self.assertRaisesRegex(RuntimeError, "TEST expired"):
                presenter_observation_records(self.request, self.runtime, identities, deadline)

    def test_png_proof_transport_is_exact_lossless_json_not_stringified_bytes(self) -> None:
        """A real PNG byte inventory must survive JSON after otherwise successful work."""
        record = presenter_observation_records(self.request, self.runtime, self.fixture.identities(), PrefixDeadline(5))
        decoded = json.loads(json.dumps(record))
        png = decoded["presenterObservations"][0]["pngMetadata"]
        self.assertEqual(png["metadataEncoding"], "hex")
        original = self.fixture.observed.evidence.png_metadata
        self.assertEqual(tuple((kind, bytes.fromhex(payload)) for kind, payload in png["metadata"]), original.metadata)
        source = decoded["presenterObservations"][0]["source"]
        self.assertEqual(source["statIdentityEncoding"], "decimal-strings")
        self.assertEqual(tuple(int(part) for part in source["stat_identity"]), self.fixture.observed.source.stat_identity)
        self.assertEqual(canonical_hash(decoded), canonical_hash(record))

    def test_guard_mutation_and_changed_raw_evidence_cannot_retain_observation(self) -> None:
        """Check callbacks before final stat observations and retained-command validation."""
        identities = self.fixture.identities()
        observed = self.fixture.observed
        changed = replace(observed, evidence=replace(observed.evidence, command_sha256=("0" * 64,) * 2))
        request = replace(self.request, presenter=replace(self.request.presenter, observations=(changed,)))
        with self.assertRaisesRegex(PrefixOracleError, "evidence is invalid"):
            presenter_observation_records(request, self.runtime, identities, PrefixDeadline(5))
        def mutate() -> None:
            """Rewrite only this TEST file after the caller's hash verification."""
            self.fixture.fixture.path.write_bytes(b"TEST changed source")
        request = replace(self.request, presenter=replace(self.request.presenter, guard=mutate))
        with self.assertRaisesRegex(PrefixOracleError, "changed after"):
            presenter_observation_records(request, self.runtime, identities, PrefixDeadline(5))

    def test_base_color_requires_observed_complete_tags_not_graph_labels(self) -> None:
        """A declared setparams policy cannot supply missing source observations."""
        valid = {"color_space": "bt709", "color_primaries": "bt709", "color_transfer": "bt709", "color_range": "tv"}
        validate_presenter_base(valid)
        for key in valid:
            with self.assertRaisesRegex(PrefixOracleError, "observed BT709"):
                validate_presenter_base({**valid, key: None})

    def test_equivalent_integer_rate_and_presenter_only_command_identity(self) -> None:
        """Guided30/1 remains in proof while only the new graph argv uses30."""
        fixture = PrefixPresenterFixture(rate="30/1")
        self.addCleanup(fixture.close)
        validate_request(fixture.request, fixture.runtime)
        command = _command(fixture.request, fixture.runtime, "unused-oracle-output.mp4")
        _raw, expected = _raw_command(fixture.request, fixture.runtime, ("full", None))
        self.assertEqual(canonical_hash(command), expected)
        self.assertEqual(graph_projection(fixture.request, "full")["clock"]["frame_rate"], "30/1")
        self.assertIn("settb=expr=1/30", command[command.index("-filter_complex") + 1])

    def test_caption_tail_preserves_presenter_and_counts_indices_after_all_overlays(self) -> None:
        """Input order differs from visual order: presenter runs before a final page."""
        asset = self.root_page()
        clock = self.request.clock
        held = SimpleNamespace(binding=SimpleNamespace(frame_clock=(clock.frame_rate, 48, 64, 36)),
                               files=(SimpleNamespace(path=asset["path"], sha256="a" * 64, size_bytes=1),))
        clips = tuple({"path": f"/TEST/graphic-{start}", "outStart": start / 30, "outEnd": 1,
                       "startFrame": start, "endFrameExclusive": 30} for start in (5, 2))
        original = replace(self.request, full_clips=clips, opening_clips=clips)
        with patch("guided_caption_layers.caption_page_clips", return_value=(asset,)):
            request = caption_prefix_request(original, held)
        self.assertIs(request.presenter, original.presenter)
        command = _command(request, self.runtime, "unused-oracle-output.mp4")
        graph = command[command.index("-filter_complex") + 1]
        inputs = [command[index + 1] for index, value in enumerate(command) if value == "-i"]
        self.assertEqual(inputs[:4], [request.base.path, clips[1]["path"], clips[0]["path"], asset["path"]])
        self.assertEqual(inputs[4:], [self.fixture.observed.source.path] * 2)
        self.assertIn("[4:v]trim=", graph)
        self.assertIn("[5:v]trim=", graph)
        self.assertIn("[pl1out][ov0]overlay", graph)
        self.assertIn("[gc1][ov2]overlay", graph)
        self.assertEqual(graph_layer_policy(request)["layerPolicy"]["fullCaptionTail"], 1)

    def root_page(self) -> dict:
        """Return TEST metadata only; this method never claims a generated page."""
        return {**page(0, 48), "path": str(self.fixture.root / "TEST-page-not-media")}

    def test_legacy_oracle_result_blocks_new_encode_before_any_output(self) -> None:
        """No old proof may cover presenter work merely through a successful callback."""
        output = self.fixture.root / "blocked.mp4"
        job = PrefixCompositionJob(self.request, self.runtime, str(output), lambda: 10)
        with patch("opening_prefix_composition.verify_compositor_prefix", return_value={"schemaVersion": 1}) \
                as oracle, patch("opening_prefix_composition._execute") as execute:
            with self.assertRaisesRegex(PrefixOracleError, "schema2"):
                compose_verified_prefix(job)
        oracle.assert_called_once()
        execute.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
