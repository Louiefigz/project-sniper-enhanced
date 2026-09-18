"""Isolated worker publication faults; native/source/owner admission are TEST stubs.

These cases test the actual adapter and byte publisher, not source authority.
Only exact allowlisted canonical regular single-link TEST output files may be
mutated. No shared dependency, source, pipeline, tool or media process is used.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr
from io import StringIO
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cross_runtime_canonical_json import canonical_compact_json
from cut_manifestation_authority import MANIFESTATION_NAME
from cut_preview_io import digest, file_hash
from guided_opening_execution import OpeningExecutionClock, opening_clock
import guided_opening_execution as clock_module
from guided_opening_prepare import OpeningPreparation
from guided_source_color_base_context import SourceColorBaseContext
import guided_source_color_media as adapter
import guided_source_color_media_evidence as evidence
import guided_opening_media as worker


class SourceColorAdapterEntryTests(unittest.TestCase):
    """The same real phase clock is used, with only original-owner/native leaves stubbed."""

    def test_original_invocation_cannot_change_during_lifetime_capture(self) -> None:
        """A retained frozen transport cannot be rebaselined by the first original callback."""
        value = adapter.SourceColorMediaInvocation(Path("/TEST/initial/input.json"), "a" * 64,
            Path("/TEST/producer"), Path("/TEST/resource"))
        lifetime, prepared, context = SimpleNamespace(guard=Mock()), object(), object()

        def changed(*_arguments: object) -> object:
            """Mutate only the actual TEST argument object, not files or source metadata."""
            object.__setattr__(value, "input_path", Path("/TEST/changed/input.json"))
            return lifetime

        with ExitStack() as stack:
            stack.enter_context(patch.object(adapter, "assert_source_color_plan"))
            stack.enter_context(patch.object(adapter, "OpeningSourceLifetime", side_effect=changed))
            observed = stack.enter_context(patch.object(adapter, "observe_opening_source_colors", return_value=object()))
            stack.enter_context(patch.object(adapter, "hold_bt709_base_identity", return_value=object()))
            constructor = stack.enter_context(patch.object(adapter, "SourceColorBaseContext", return_value=context))
            constructor.assert_current = Mock()
            stack.enter_context(patch.object(adapter, "prepare_source_color_full_program", return_value=prepared))
            with self.assertRaisesRegex(RuntimeError, "original|invocation|changed"):
                adapter.prepare_source_color_media(object(), object(), (Path("/TEST/output"), opening_clock(20), {}), value)
        observed.assert_not_called()


class SourceColorEvidenceOriginalFileTests(unittest.TestCase):
    """Use real bounded output reads/writes with explicit source/live-owner qualification stubs."""

    def setUp(self) -> None:
        """Create a disjoint TEST-only output namespace before any hold begins."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-color-evidence-fault-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        base_dir = self.root / "full-program-base"
        base_dir.mkdir(mode=0o700)
        self.paths = {"base": base_dir / "final.mp4", "timeline": base_dir / "timeline_map.json",
            "manifestation": base_dir / MANIFESTATION_NAME, "master": base_dir / "master-receipt.json"}
        self.allowed = frozenset(self.paths.values())
        self._create("base", b"TEST original generated output, not media")
        self._create("timeline", b'{"TEST":"timeline"}')
        self._create("manifestation", canonical_compact_json({"receiptHash": "c" * 64,
            "timelineMapSha256": file_hash(self.paths["timeline"])}).encode())
        picture = {"TEST": "copy observation supplied by original-owner stub"}
        body = {"kind": "ordinary-source-float-master", "approved": False, "path": str(self.paths["base"]),
            "sha256": file_hash(self.paths["base"]), "picture": picture}
        self.master = {**body, "receiptHash": digest(body)}
        self._create("master", canonical_compact_json(self.master).encode())
        refs = {name: {"path": str(path), "sha256": file_hash(path)} for name, path in self.paths.items()}
        self.prepared = OpeningPreparation(self.paths["base"], object(), {"base": refs["base"],
            "receipts": {"cutManifestation": refs["manifestation"], "timelineMap": refs["timeline"]}})
        self.context = object.__new__(SourceColorBaseContext)
        self.consumed = {"manifestation": {"receiptHash": "c" * 64}, "pictureCopy": picture,
            "basePublication": {"receiptPath": str(self.paths["master"]), "receipt": self.master}}

    def _create(self, key: str, raw: bytes) -> None:
        """Initial writes are new-only and restricted to the exact TEST output allowlist."""
        path = self.paths[key]
        if path not in self.allowed or path.parent.resolve() != self.root / "full-program-base":
            raise AssertionError("unsafe TEST initial artifact target")
        with path.open("xb") as handle:
            handle.write(raw)

    def _change(self, key: str) -> None:
        """Fault only a canonical unaliased regular TEST-owned generated output."""
        path = self.paths[key]
        info = path.lstat()
        if path not in self.allowed or path.resolve(strict=True) != path or not path.is_relative_to(self.root) \
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise AssertionError("unsafe TEST artifact mutation target")
        path.write_bytes(b"TEST generated artifact changed after original byte read")

    def fault(self, key: str) -> None:
        """Run actual file/hash publication; only source provenance and original guard are stubbed."""
        calls = []

        def guard(_context: object) -> None:
            """The second actual prepublication check follows full generated-artifact reads."""
            calls.append(True)
            if len(calls) == 2:
                self._change(key)

        owner = SimpleNamespace(context=SimpleNamespace(opening=SimpleNamespace(value={"outputRoot": str(self.root)})))
        with ExitStack() as stack:
            stack.enter_context(patch.object(evidence, "_opening", return_value=owner))
            stack.enter_context(patch.object(SourceColorBaseContext, "assert_metadata"))
            stack.enter_context(patch.object(SourceColorBaseContext, "assert_current", side_effect=guard))
            stack.enter_context(patch.object(SourceColorBaseContext, "consumption_record", return_value=self.consumed))
            stack.enter_context(patch.object(evidence, "project_source_color_observations", return_value={"TEST": "source stub"}))
            with self.assertRaisesRegex(RuntimeError, "changed|artifact|base|publication"):
                evidence.write_source_color_media_evidence(self.context, self.prepared, self.root)

    def test_final_original_callback_cannot_change_already_read_base_bytes(self) -> None:
        """Source-lifetime validity does not substitute for generated-output byte lifetime."""
        self.fault("base")

    def test_final_original_callback_cannot_change_already_read_master_receipt(self) -> None:
        """The original master return and already-read receipt file must remain joined."""
        self.fault("master")


class SourceColorCompletionClockTests(unittest.TestCase):
    """Actual outer phase timers with a TEST monotonic observer and no file/native work."""

    def completion_fixture(self) -> tuple:
        """Stub only original source/native/output qualification while retaining actual worker flow."""
        inputs = SimpleNamespace(value={"executionId": "TEST", "executionInputHash": "a" * 64},
            sha256="b" * 64, documents={"authority": {}})
        prepared = SimpleNamespace(captions=None, base=Path("/TEST/base"),
            selection=SimpleNamespace(master=SimpleNamespace(source_bus=SimpleNamespace(admission=SimpleNamespace(tools={})))))
        claim = SimpleNamespace(sha256="c" * 64)
        values = {"_audio": {}, "screen_context": None, "render_opening_graphics": {"clips": [], "evidence": {}},
            "compose_ranges": {}, "mux_ranges": {}, "_unchanged": None, "_receipt": {"receiptHash": "d" * 64},
            "write_source_color_media_evidence": {"TEST": "held evidence"}, "verify_source_color_media_evidence": None}
        return inputs, prepared, claim, values

    def receipt_root(self) -> Path:
        """Create one actual private TEST receipt so initial stat/read holds remain real."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-completion-tail-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        with (root / "media-result.json").open("xb") as handle:
            handle.write(b'{"TEST":"original generated receipt, not media proof"}')
        return root

    def test_last_completion_hash_cannot_cross_original_clock(self) -> None:
        """The final receipt SHA is work, not a free unchecked tail after the last phase."""
        now, clock = [0.0], OpeningExecutionClock(20.0)
        inputs, prepared, claim, values = self.completion_fixture()
        root, original_hash = self.receipt_root(), worker.file_hash

        def expired(path: Path) -> str:
            """Advance only the TEST monotonic clock during the final actual completion hash call."""
            observed = original_hash(path)
            now[0] = 21.0
            return observed

        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(StringIO()))
            stack.enter_context(patch.object(clock_module.time, "monotonic", side_effect=lambda: now[0]))
            for name, result in values.items():
                stack.enter_context(patch.object(worker, name, return_value=result))
            stack.enter_context(patch.object(worker, "file_hash", side_effect=expired))
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                worker._finish_execution(inputs, root, clock, (claim, {}, [], prepared, object()))

    def test_final_source_guard_cannot_change_hashed_completion_receipt(self) -> None:
        """The final original callback must not invalidate the raw SHA already placed in completion."""
        root = self.receipt_root()
        receipt = root / "media-result.json"
        inputs, prepared, claim, values = self.completion_fixture()

        def changed(_context: object) -> None:
            """Mutate only this exact canonical single-link TEST-owned output after its actual hash."""
            info = receipt.lstat()
            if receipt != root / "media-result.json" or receipt.resolve(strict=True) != receipt \
                    or receipt.parent != root or not stat.S_ISREG(info.st_mode) \
                    or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise AssertionError("unsafe TEST completion mutation target")
            receipt.write_bytes(b'{"TEST":"changed during final original source callback"}')

        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(StringIO()))
            for name, result in values.items():
                stack.enter_context(patch.object(worker, name, return_value=result))
            stack.enter_context(patch.object(worker.SourceColorBaseContext, "assert_current", side_effect=changed))
            with self.assertRaisesRegex(RuntimeError, "changed|receipt|artifact"):
                worker._finish_execution(inputs, root, opening_clock(20), (claim, {}, [], prepared, object()))


if __name__ == "__main__":
    unittest.main()
