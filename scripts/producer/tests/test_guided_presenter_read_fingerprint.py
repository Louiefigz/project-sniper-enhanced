"""Private guard equivalence over tiny TEST pins; no decoder or renderer."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
import unittest
from unittest.mock import patch

from _guided_presenter_read_fixture import PresenterReadFixture
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
import guided_presenter_read as module


@dataclass(frozen=True)
class _Record:
    """Deliberately mutable via object.__setattr__, like any frozen Python record."""

    data: tuple


class ReadMetadataTests(unittest.TestCase):
    """Snapshots preserve type distinctions that JSON receipt equality normalizes."""

    def test_detached_json_sequence_and_record_fields(self) -> None:
        """Neither mutable descendants nor frozen record identity can hide drift."""
        value = {"record": _Record(([1, 2.0, True],)), "text": "TEST 🐈 \ud800"}
        held = hold_read_metadata(value)
        self.assertTrue(same_read_metadata(deepcopy(value), held))
        value["record"].data[0].append(3)
        self.assertFalse(same_read_metadata(value, held))

    def test_equal_valued_types_and_signed_zero_are_distinct(self) -> None:
        """Integral floats, booleans, tuple/list and stat integer spelling stay exact."""
        pairs = ((1, 1.0), (1, True), (0.0, -0.0), ([1], (1,)),
                 (b"TEST", "TEST"), (_Record((1,)), _Record((1.0,))))
        for original, changed in pairs:
            with self.subTest(original=original):
                self.assertFalse(same_read_metadata(changed, hold_read_metadata(original)))

    def test_mapping_order_is_irrelevant_but_fields_are_closed(self) -> None:
        """Insertion order never changes receipt meaning; omission and additions do."""
        held = hold_read_metadata({"a": 1, "b": False})
        self.assertTrue(same_read_metadata({"b": False, "a": 1}, held))
        self.assertFalse(same_read_metadata({"a": 1}, held))
        self.assertFalse(same_read_metadata({"a": 1, "b": False, "c": None}, held))

    def test_frozen_record_mutation_cannot_change_held_snapshot(self) -> None:
        """A snapshot retains detached field values, not an alias to a dataclass."""
        value = _Record((1, b"TEST", 10 ** 18))
        held = hold_read_metadata(value)
        object.__setattr__(value, "data", (1, b"TEST", 10 ** 18 + 1))
        self.assertFalse(same_read_metadata(value, held))

    def test_unsupported_and_nonfinite_metadata_reject(self) -> None:
        """This private helper is not arbitrary object serialization."""
        for value in (float("nan"), float("inf"), {1: "TEST"}, object(), _Record):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hold_read_metadata(value)


class PresenterReadGuardTests(unittest.TestCase):
    """Exercise unchanged source callbacks around optimized metadata comparisons."""

    def setUp(self) -> None:
        """Use owned tiny TEST files and stubbed original probe evidence only."""
        self.fixture = PresenterReadFixture()
        self.addCleanup(self.fixture.close)

    def assert_mutation_rejects(self, mutate: Callable[[module.PresenterReadContext, dict], None]) -> None:
        """Mutate detached TEST metadata only, after the actual original guard."""
        original = self.fixture.context
        context = replace(original, inputs=deepcopy(original.inputs), base=deepcopy(original.base),
                          ffprobe=deepcopy(original.ffprobe))
        arguments = {"TEST": [1, 2.0, True]}

        def changed() -> None:
            """Retain the real original source/clock check before a late mutation."""
            original.guard()
            mutate(context, arguments)

        context = replace(context, guard=changed)
        check = module._read_guard(context, arguments)
        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            check()

    def test_hot_callbacks_do_not_recanonicalize_or_revalidate_references(self) -> None:
        """Every caller guard remains; receipt constructors run only at admission."""
        calls = 0

        def counted() -> None:
            """Count without replacing or resetting the real source/deadline guard."""
            nonlocal calls
            calls += 1
            self.fixture.guard()

        context = replace(self.fixture.context, guard=counted)
        check = module._read_guard(context, {"TEST": [1, False]})
        with patch.object(module, "canonical_hash", side_effect=AssertionError("no hot receipt hash")), \
                patch.object(module, "capture_input_binding", side_effect=AssertionError("no hot binding hash")), \
                patch.object(module, "_reference_identity", side_effect=AssertionError("no hot reference validation")), \
                patch.object(module, "_captured_identity", side_effect=AssertionError("no hot capture validation")):
            check()
            check()
            check()
        self.assertEqual(calls, 3)

    def test_initial_json_domain_and_original_invalid_refs_still_reject(self) -> None:
        """Private record snapshots do not admit tuples/bytes/unsafe integers as JSON."""
        for value in ((1,), b"TEST", 1 << 54, float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module._read_guard(self.fixture.context, {"TEST": value})
        bad = replace(self.fixture.context, ffprobe=replace(self.fixture.tool, size_bytes=True))
        with self.assertRaises(ValueError):
            module._read_guard(bad, {})

    def test_late_input_and_argument_numeric_container_and_field_changes_reject(self) -> None:
        """Catch exact metadata changes after the original guard, not just hashes."""
        mutations = (
            lambda ctx, args: ctx.inputs.documents["authority"].update(totalFrames=48.0),
            lambda ctx, args: args["TEST"].__setitem__(0, True),
            lambda ctx, args: args.update(TEST=tuple(args["TEST"])),
            lambda ctx, args: args.update(extra=None),
            lambda ctx, args: object.__setattr__(ctx.inputs, "sha256", "0" * 64),
        )
        for mutate in mutations:
            self.assert_mutation_rejects(mutate)

    def test_late_full_capture_fields_and_exact_stat_types_reject(self) -> None:
        """No detached entries, nanosecond precision loss or same-object mutation."""
        mutations = (
            lambda ctx, args: object.__setattr__(ctx.inputs.verified_media, "entries_json", b"[]"),
            lambda ctx, args: object.__setattr__(ctx.inputs.verified_media.snapshots[0], "sha256", "d" * 64),
            lambda ctx, args: object.__setattr__(ctx.inputs.verified_media.snapshots[0], "stat_identity",
                (*ctx.inputs.verified_media.snapshots[0].stat_identity[:-1], 1.0)),
            lambda ctx, args: object.__setattr__(ctx.inputs.verified_media, "snapshots",
                list(ctx.inputs.verified_media.snapshots)),
        )
        for mutate in mutations:
            self.assert_mutation_rejects(mutate)

    def test_late_base_tool_fields_and_context_identity_reject(self) -> None:
        """Frozen-reference corruption and equal replacement input/capture are fenced."""
        mutations = (
            lambda ctx, args: object.__setattr__(ctx.base, "size_bytes", float(ctx.base.size_bytes)),
            lambda ctx, args: object.__setattr__(ctx.ffprobe, "stat_identity", tuple(float(x) for x in ctx.ffprobe.stat_identity)),
            lambda ctx, args: object.__setattr__(ctx.ffprobe, "path", ctx.ffprobe.path + "-changed"),
            lambda ctx, args: object.__setattr__(ctx, "inputs", deepcopy(ctx.inputs)),
            lambda ctx, args: object.__setattr__(ctx.inputs, "verified_media", deepcopy(ctx.inputs.verified_media)),
            lambda ctx, args: object.__setattr__(ctx, "guard", lambda: None),
        )
        for mutate in mutations:
            self.assert_mutation_rejects(mutate)

    def test_source_callback_error_and_original_deadline_propagate_unchanged(self) -> None:
        """Neither an exception nor an expired clock can be replaced by clean metadata."""
        error = RuntimeError("TEST original source lifetime is closed")

        def closed() -> None:
            """Propagate the exact original ownership error without a new verdict."""
            raise error

        context = replace(self.fixture.context, guard=closed)
        check = module._read_guard(context, {})
        with self.assertRaises(RuntimeError) as caught:
            check()
        self.assertIs(caught.exception, error)
        check = module._read_guard(self.fixture.context, {})
        self.fixture.probe.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            check()


if __name__ == "__main__":
    unittest.main()
