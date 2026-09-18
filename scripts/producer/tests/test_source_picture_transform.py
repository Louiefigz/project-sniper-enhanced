"""Closed non-executable compiler tests; no fake source/approval is qualified."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from unittest.mock import patch

from _source_picture_transform_fixture import no_authority_guard, transform_fixture
from color.source_picture_transform import compile_source_picture_transform
from color.source_picture_transform_contract import bounded_json
from cut_preview_io import digest


class SourcePictureTransformTests(unittest.TestCase):
    """Bind every input without giving a compiled filter execution authority."""

    def test_one_frame_integer_and_ntsc_keep_native_nonzero_clock(self) -> None:
        """One-frame cases must not round a rational rate or reset source origin."""
        for rate in ("24", "24000/1001", "30000/1001"):
            context, intent = transform_fixture(rate, 1)
            result = compile_source_picture_transform(context, intent, no_authority_guard)
            row = result.record()
            clock = row["bindings"]["observation"]["clock"]
            self.assertEqual((clock["fps"], clock["frames"], clock["firstPts"]), (rate, 1, 24000))
            self.assertEqual((clock["width"], clock["height"]), (8, 4))
            self.assertFalse(row["executable"])
            self.assertFalse(row["gradeApproved"])
            self.assertFalse(row["deliveryApproved"])
            self.assertEqual(row["gamutTolerance"], 0)
            self.assertIn("not-supplied", row["gamutProof"])
            with self.assertRaises(FrozenInstanceError):
                result.executable = True

    def test_filter_is_explicit_float_bridge_without_geometry_audio_or_look_ops(self) -> None:
        """No implicitly selected input tags, lib gamma approximation or LUT."""
        context, intent = transform_fixture()
        result = compile_source_picture_transform(context, intent, no_authority_guard)
        for token in ("tin=iec61966-2-4", "pin=bt709", "min=bt709", "rin=tv", "cin=left",
                      "t=linear", "r=full", "agamma=0", "filter=bilinear", "dither=none", "format=gbrpf32le"):
            self.assertIn(token, result.measurement_filter)
        self.assertIn("tin=linear", result.destination_filter)
        self.assertIn("t=bt709:m=bt709:r=tv:c=left,format=yuv420p", result.destination_filter)
        for token in ("setpts", "fps=", "crop", "scale=1920", "setparams", "lut", "tonemap", "loudnorm", "npl="):
            self.assertNotIn(token, result.measurement_filter + result.destination_filter)

    def test_unknown_keys_policy_waivers_and_bool_schema_reject(self) -> None:
        """Raw filters or a tolerance cannot slip through the closed policy."""
        context, intent = transform_fixture()
        for key, value in (("filter", "null"), ("approved", True), ("gamutTolerance", 0.01),
                           ("schemaVersion", True), ("gamutPolicy", "clip"), ("quantization", "guess")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                compile_source_picture_transform(context, {**intent, key: value}, no_authority_guard)

    def test_every_source_parent_and_tool_identity_affects_or_rejects_binding(self) -> None:
        """Exact semantic identities are retained, not only the transfer label."""
        context, intent = transform_fixture()
        before = compile_source_picture_transform(context, intent, no_authority_guard)
        changed = copy.deepcopy(context.authority)
        changed["expectedParents"]["planSha256"] = "6" * 64
        after = compile_source_picture_transform(replace(context, authority=changed), intent, no_authority_guard)
        self.assertNotEqual(before.input_hash, after.input_hash)
        for key in ("ffmpeg", "libavfilter", "libzimg"):
            tools = copy.deepcopy(context.tools)
            tools[key]["sha256"] = "a" * 64
            result = compile_source_picture_transform(replace(context, tools=tools), intent, no_authority_guard)
            self.assertNotEqual(before.input_hash, result.input_hash)
        changed["source"]["sha256"] = "5" * 64
        with self.assertRaisesRegex(ValueError, "source/history"):
            compile_source_picture_transform(replace(context, authority=changed), intent, no_authority_guard)

    def test_observation_source_probe_raw_records_and_execution_are_bound(self) -> None:
        """None of the independently retained original observation refs is lost."""
        context, intent = transform_fixture()
        original = compile_source_picture_transform(context, intent, no_authority_guard)
        for field in ("raw_probe_sha256", "raw_frames_sha256", "execution_sha256"):
            held = replace(context.observation, **{field: "0" * 64})
            changed = compile_source_picture_transform(replace(context, observation=held), intent, no_authority_guard)
            self.assertNotEqual(original.input_hash, changed.input_hash)
        bad = replace(context.observation.records.source, admission_receipt_sha256="0" * 64)
        held = replace(context.observation, records=replace(context.observation.records, source=bad))
        with self.assertRaisesRegex(ValueError, "source/coverage"):
            compile_source_picture_transform(replace(context, observation=held), intent, no_authority_guard)

    def test_metadata_missing_unknown_mixed_sar_and_bad_clock_reject(self) -> None:
        """A legacy/partial source observation cannot be promoted to this class."""
        context, intent = transform_fixture()
        original = context.observation.records.stream
        metadata = original.source_metadata
        variants = [None, replace(metadata, stream_chroma_location="unavailable"),
            replace(metadata, decoded_chroma_location="unavailable"),
            replace(metadata, decoded_chroma_location="center"),
            replace(metadata, decoded_sample_aspect_ratio="unavailable"),
            replace(metadata, stream_sample_aspect_ratio="4:3", decoded_sample_aspect_ratio="4:3")]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                self._compile_stream(context, intent, replace(original, source_metadata=variant))
        for variant in (replace(original, step_ticks=1), replace(original, time_base=Fraction(1, 1)),
                        replace(original, width=8192), replace(original, first_pts=True)):
            with self.assertRaises(ValueError):
                self._compile_stream(context, intent, variant)

    def _compile_stream(self, context: object, intent: dict, stream: object) -> None:
        """Keep each malformed stream isolated in explicitly synthetic metadata."""
        records = replace(context.observation.records, stream=stream)
        held = replace(context.observation, records=records)
        compile_source_picture_transform(replace(context, observation=held), intent, no_authority_guard)

    def test_unknown_profile_history_and_resealed_mismatched_history_reject(self) -> None:
        """The compiler never interprets history prose as a known transform."""
        for key in ("historyState", "sourceProfile"):
            context, intent = transform_fixture()
            context.authority["declaration"][key] = "unknown"
            context.authority["binding"]["declarationSha256"] = digest(context.authority["declaration"])
            with self.assertRaisesRegex(ValueError, "known declared history"):
                compile_source_picture_transform(context, intent, no_authority_guard)
        context, intent = transform_fixture()
        context.authority["projectHistory"]["projectSha256"] = "0" * 64
        context.authority["binding"]["projectHistorySha256"] = digest(context.authority["projectHistory"])
        with self.assertRaisesRegex(ValueError, "bound parents"):
            compile_source_picture_transform(context, intent, no_authority_guard)

    def test_source_path_alias_and_tool_version_mismatch_reject_before_io(self) -> None:
        """Pure compilation neither opens paths nor invokes a tool as fallback."""
        for path in ("relative", "/tmp//x", "/tmp/./x", "/tmp/../x", "/tmp/x\n", "/tmp/x\\y"):
            context, intent = transform_fixture()
            context.authority["source"]["path"] = path
            with self.assertRaises(ValueError):
                compile_source_picture_transform(context, intent, no_authority_guard)
        context, intent = transform_fixture()
        context.tools["zimgVersion"] = "3.0.5"
        with patch("subprocess.Popen", side_effect=AssertionError("no child")), self.assertRaises(ValueError):
            compile_source_picture_transform(context, intent, no_authority_guard)

    def test_owner_expiry_and_late_context_mutation_never_return_plan(self) -> None:
        """Every guard is the caller's original budget, not a fresh allocation."""
        context, intent = transform_fixture()
        with self.assertRaisesRegex(TimeoutError, "original"):
            compile_source_picture_transform(context, intent, lambda: (_ for _ in ()).throw(TimeoutError("original")))
        calls = []

        def mutate_on_last_guard() -> None:
            """Simulate an authority race after the held hash was computed."""
            calls.append(1)
            if len(calls) == 3:
                context.authority["expectedParents"]["planSha256"] = "0" * 64

        with self.assertRaisesRegex(RuntimeError, "changed before return"):
            compile_source_picture_transform(context, intent, mutate_on_last_guard)

    def test_context_and_status_json_do_not_get_invocation_provenance(self) -> None:
        """No decoder execution or selectable artifact can be minted by this API."""
        context, intent = transform_fixture()
        with self.assertRaisesRegex(ValueError, "live bound"):
            compile_source_picture_transform(replace(context, observation={"status": "complete"}), intent, no_authority_guard)
        result = compile_source_picture_transform(context, intent, no_authority_guard)
        detached = result.record()
        detached["bindings"]["intent"]["gamutPolicy"] = "clip"
        self.assertEqual(result.record()["bindings"]["intent"]["gamutPolicy"], "reject-out-of-gamut")
        self.assertIn("requires-owned", result.record()["toolClosureVerification"])

    def test_equal_observation_reconstruction_during_final_guard_rejects(self) -> None:
        """Relational equality cannot replace the separately retained live object."""
        context, intent = transform_fixture()
        calls = []

        def replace_on_last_guard() -> None:
            """Simulate an accidental cold reconstruction at the final boundary."""
            calls.append(1)
            if len(calls) == 3:
                object.__setattr__(context, "observation", replace(context.observation))

        with self.assertRaisesRegex(RuntimeError, "changed before return"):
            compile_source_picture_transform(context, intent, replace_on_last_guard)

    def test_depth_size_cycle_nonfinite_and_oversized_context_fail_bounded(self) -> None:
        """Context canonicalization is bounded before recursive serialization."""
        cycle = []
        cycle.append(cycle)
        for value in (cycle, [0] * 4097, {"large": "x" * 131073}, {"amount": float("nan")}, {"amount": 10 ** 100}):
            with self.subTest(kind=type(value)), self.assertRaises(ValueError):
                bounded_json(value)
