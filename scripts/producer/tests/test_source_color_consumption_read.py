"""Actual cold joins and packet parsers over inert owned TEMP artifacts only."""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import os
import unittest
from unittest.mock import patch

from _source_color_consumption_read_fixture import ConsumptionReadFixture
from audio import audio_mix_picture
from cut_preview_io import digest
import guided_source_color_consumption_read as reader


class ConsumptionReadTests(unittest.TestCase):
    """Caller provenance and ffprobe are TEST leaves; all cold joins and file holds are real."""

    def setUp(self) -> None:
        """Own a fresh exact TEMP tree and never pin or mutate production dependencies."""
        self.f = object.__new__(ConsumptionReadFixture)
        self.addCleanup(self.f.cleanup)
        self.f.__init__()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": str(self.f.tools)}))
        self.native = self.stack.enter_context(patch.object(audio_mix_picture, "_run", side_effect=self.f.native))

    def hold(self) -> object:
        """Exercise actual finite reader under the fixture's original unrenewed cutoff."""
        return reader.hold_source_color_consumption(self.f.evidence, self.f.context)

    def negative(self, mutation: object) -> None:
        """Change only pre-entry authenticated TEST data; all malformed intent must fail early."""
        mutation()
        self.f.reseal()
        with self.assertRaises((RuntimeError, ValueError, KeyError, TypeError)):
            self.hold()
        self.native.assert_not_called()

    def test_actual_compiler_manifestation_packet_and_publication_joins(self) -> None:
        """Repeat sources remain ordered and native probes see only master/final generated paths."""
        held = self.hold()
        self.assertEqual(held.record, self.f.consumed)
        self.assertIsNot(held.record, self.f.consumed)
        self.assertEqual([row["segment"]["source_id"] for row in held.record["cuts"]], ["raw-b", "raw-a", "raw-b"])
        self.assertEqual(len(self.f.native_calls), 3)
        self.assertFalse(held.record["colorQualified"])
        self.assertFalse(held.record["deliveryApproved"])
        count = self.native.call_count
        held.check()
        held.assert_metadata()
        self.assertEqual(self.native.call_count, count)

    def test_missing_repeated_cut_refuses_before_native(self) -> None:
        """A source-level set cannot stand in for every actual ordered encode occurrence."""
        self.negative(lambda: self.f.consumed["cuts"].pop())

    def test_reordered_cut_refuses_before_native(self) -> None:
        """Same source/count metadata cannot hide a swapped occurrence."""
        self.negative(lambda: self.f.consumed["cuts"].reverse())

    def test_boolean_frame_count_refuses_before_native(self) -> None:
        """Strict numeric types must not treat True as an accepted integer frame count."""
        self.negative(lambda: self.f.consumed["cuts"][0].update(frames=True))

    def test_changed_source_declaration_refuses_before_native(self) -> None:
        """Every occurrence retains original declaration and admission raw identities."""
        self.negative(lambda: self.f.consumed["cuts"][0]["source"].update(declarationSha256="0" * 64))

    def test_wrong_master_input_refuses_before_native(self) -> None:
        """A same-length arbitrary picture cannot replace the exact original concat."""
        self.negative(lambda: self.f.consumed["master"].update(inputPath=str(self.f.paths["base"])))

    def test_master_burn_or_changed_picture_profile_refuses_before_native(self) -> None:
        """Unrecorded caption/profile changes cannot be laundered through master metadata."""
        self.negative(lambda: self.f.consumed["master"].update(ass="TEST-burn.ass"))

    def test_recorded_argv_is_bounded_data_not_executable(self) -> None:
        """Even executable-looking commands are ignored; wrong input/output joins reject."""
        self.negative(lambda: self.f.consumed["master"]["argv"].append("TEST-other-output"))

    def test_nested_approval_field_refuses_before_native(self) -> None:
        """Closed consumed cut records cannot gain an approval flag through unknown JSON."""
        self.negative(lambda: self.f.consumed["cuts"][0].update(colorApproved=True))

    def test_wrong_original_full_base_refuses_before_native(self) -> None:
        """Separately held schema2 full-program refs are never replaced by section self-hashes."""
        self.f.bindings["fullProgram"] = deepcopy(self.f.bindings["fullProgram"])
        self.f.bindings["fullProgram"]["base"]["sha256"] = "0" * 64
        self.assertRaises((RuntimeError, ValueError), self.hold)
        self.native.assert_not_called()

    def test_first_callback_cannot_replace_later_master_file(self) -> None:
        """Every generated file is captured before the first caller callback."""
        self.f.on_guard = lambda: self.f.change(self.f.paths["pictureMaster"], b"TEST substituted")
        self.assertRaisesRegex(RuntimeError, "changed", self.hold)
        self.native.assert_not_called()

    def test_after_native_callback_cannot_rebaseline_final_base(self) -> None:
        """A generated file modified after native work remains bound to its initial stat/hash."""
        def mutate() -> None:
            """Modify only the exact allowlisted TEMP base after the first native packet observation."""
            if self.f.native_calls:
                self.f.change(self.f.paths["base"], b"TEST post-native substitution")
        self.f.on_guard = mutate
        self.assertRaisesRegex(RuntimeError, "changed", self.hold)
        self.assertEqual(self.native.call_count, 2)

    def test_held_check_detects_later_byte_change_without_native(self) -> None:
        """Later AV callbacks cannot replace retained artifacts without another probe being needed."""
        held = self.hold()
        count = self.native.call_count
        self.f.change(self.f.paths["sourceBus"], b"TEST changed original bus")
        self.assertRaisesRegex(RuntimeError, "changed", held.assert_metadata)
        self.assertEqual(self.native.call_count, count)

    def test_late_returned_native_object_mutation_is_retained(self) -> None:
        """Actual PictureSource return fields remain held through later outer AV stages."""
        actual, original = [], reader.observe_picture_source
        def observe(*args: object) -> object:
            """Retain the real native-parser return so only TEST object state can be faulted."""
            result = original(*args)
            actual.append(result)
            return result
        with patch.object(reader, "observe_picture_source", side_effect=observe):
            held = self.hold()
        object.__setattr__(actual[0], "sha256", "0" * 64)
        self.assertRaisesRegex(RuntimeError, "metadata changed", held.assert_metadata)

    def test_native_copy_packet_difference_refuses(self) -> None:
        """Actual packet-copy comparison rejects differing final coded bytes/timestamps."""
        original = self.f.native
        def changed(argv: list[str]) -> object:
            """Alter only explicit TEST ffprobe stdout for the generated final file."""
            result = original(argv)
            if argv[-1] == str(self.f.paths["base"]):
                result.stdout = result.stdout.replace("d" * 64, "e" * 64)
            return result
        self.native.side_effect = changed
        self.assertRaisesRegex(RuntimeError, "packets|PTS", self.hold)

    def test_original_context_and_returned_record_cannot_be_substituted(self) -> None:
        """A retained lifetime must notice replacement even by an equal detached DTO."""
        held = self.hold()
        held.record = deepcopy(held.record)
        self.assertRaisesRegex(RuntimeError, "metadata changed", held.assert_metadata)

    def test_same_original_deadline_closes_final_metadata_without_guard(self) -> None:
        """No retained check renews allowance and pure final checks invoke no arbitrary callback."""
        held = self.hold()
        before = self.f.calls
        with patch("color.deadline.time.monotonic", return_value=self.f.context.deadline + 1):
            self.assertRaisesRegex(RuntimeError, "deadline", held.assert_metadata)
        self.assertEqual(self.f.calls, before)

    def test_changed_path_tool_mapping_refuses_before_native(self) -> None:
        """Literal ffprobe resolves only to the original caller-authenticated PATH tool."""
        with patch.dict(os.environ, {"PATH": str(self.f.directory)}):
            self.assertRaisesRegex(RuntimeError, "ffprobe", self.hold)
        self.native.assert_not_called()

    def test_manifestation_boolean_source_time_does_not_equal_numeric_zero(self) -> None:
        """Existing mathematical proof alone must not permit JSON bool/int coercion."""
        record = deepcopy(self.f.manifestation)
        record["parts"][0]["srcStart"] = False
        record["receiptHash"] = digest({key: row for key, row in record.items() if key != "receiptHash"})
        self.f.change(self.f.paths["cutManifestation"], self.f.raw(record))
        reference = self.f.ref(self.f.paths["cutManifestation"])
        self.f.evidence["fullProgram"]["cutManifestation"] = reference
        self.f.bindings["fullProgram"]["receipts"]["cutManifestation"] = reference
        self.f.consumed["manifestation"].update(parts=record["parts"], receiptHash=record["receiptHash"])
        self.f.reseal()
        self.assertRaises((RuntimeError, ValueError), self.hold)
        self.native.assert_not_called()

    def test_last_original_callback_cannot_change_evidence_bytes(self) -> None:
        """The actual final callback is followed by all original file checks, not a fresh baseline."""
        def mutate() -> None:
            """Touch only the allowlisted TEMP section after the complete packet-copy proof."""
            if self.f.calls == 7:
                self.f.change(self.f.paths["evidence"], b"TEST final-callback bytes")
        self.f.on_guard = mutate
        self.assertRaisesRegex(RuntimeError, "changed", self.hold)
        self.assertEqual((self.f.calls, self.native.call_count), (7, 3))

    def test_late_actual_copy_proof_return_mutation_is_retained(self) -> None:
        """Later outer work cannot change a real returned copy proof without a second native read."""
        actual, original = [], reader.verify_picture_copy
        def verify(*args: object) -> dict:
            """Keep the real existing verifier return; only TEST object mutation follows."""
            result = original(*args)
            actual.append(result)
            return result
        with patch.object(reader, "verify_picture_copy", side_effect=verify):
            held = self.hold()
        actual[0]["picturePackets"] = 17
        self.assertRaisesRegex(RuntimeError, "metadata changed", held.assert_metadata)

    def test_equal_context_binding_replacement_during_callback_refuses(self) -> None:
        """Type/value equality does not authorize adoption of a substituted original container."""
        self.f.on_guard = lambda: object.__setattr__(self.f.context, "bindings", deepcopy(self.f.context.bindings))
        self.assertRaisesRegex(RuntimeError, "metadata changed", self.hold)
        self.native.assert_not_called()

    def test_last_original_callback_cannot_extend_original_deadline(self) -> None:
        """The single caller cutoff is retained even if a callback substitutes a larger value."""
        def extend() -> None:
            """Change only an in-memory TEST context after existing packet work completed."""
            if self.f.calls == 7:
                object.__setattr__(self.f.context, "deadline", self.f.context.deadline + 60)
        self.f.on_guard = extend
        self.assertRaisesRegex(RuntimeError, "metadata changed", self.hold)

    def test_data_only_wrapper_is_detached_but_not_execution_authority(self) -> None:
        """Convenience callers get JSON only, without constructing a recorder or native owner."""
        record = reader.read_source_color_consumption(self.f.evidence, self.f.context)
        self.assertEqual(record, self.f.consumed)
        self.assertIsNot(record, self.f.consumed)
        self.assertNotIn("executable", record)

    def test_completed_inventory_cannot_adopt_late_parsed_metadata(self) -> None:
        """A completed handle cannot extend its privately retained proof inventory."""
        held = self.hold()
        self.assertRaisesRegex(RuntimeError, "late parser", reader.HeldSourceColorConsumption.retain,
                               held, {"TEST": "late replacement proof"})
        held.assert_metadata()
        self.assertEqual(self.native.call_count, 3)

    def test_foreign_handle_cannot_copy_public_fields_into_a_new_lifetime(self) -> None:
        """A spread-like instance has no private original inventory despite matching visible fields."""
        held = self.hold()
        foreign = object.__new__(reader.HeldSourceColorConsumption)
        vars(foreign).update(vars(held))
        self.assertRaisesRegex(RuntimeError, "original retained", reader.HeldSourceColorConsumption.assert_metadata, foreign)
        self.assertEqual(self.native.call_count, 3)

    def test_file_metadata_row_mutation_cannot_rebaseline_private_identity(self) -> None:
        """Even a visible frozen dataclass cannot replace its private original stat snapshot."""
        held = self.hold()
        row = held.files[str(self.f.paths["base"])]
        object.__setattr__(row, "maximum", row.maximum + 1)
        self.assertRaisesRegex(RuntimeError, "metadata changed", held.assert_metadata)
        self.assertEqual(self.native.call_count, 3)


if __name__ == "__main__":
    unittest.main()
