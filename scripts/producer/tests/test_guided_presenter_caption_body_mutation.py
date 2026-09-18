"""Finite-phase mutation tests; writes are guarded exact-root TEST fixtures only."""
from __future__ import annotations

from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_presenter_caption_body_fixture import BodyCaptionPictureFixture
from guided_presenter_caption_body_picture import BodyPresenterCaptionContext, prepare_presenter_caption_body
from guided_presenter_caption_body_record import body_presenter_caption_picture_record
from guided_presenter_caption_clearance import verify_presenter_caption_clearance


class PresenterCaptionBodyMutationTests(unittest.TestCase):
    """Actual metadata/copy callbacks cannot rebaseline earlier verified evidence."""

    def setUp(self) -> None:
        """Keep independent temporary roots and no external mutation targets."""
        self.fixture = BodyCaptionPictureFixture()
        self.addCleanup(self.fixture.close)

    def test_fault_guard_rejects_external_dependency_before_write(self) -> None:
        """Never infer ownership from membership in the held external dependency list."""
        target = Path(self.fixture.held.external[0].path)
        before = target.read_bytes()
        with self.assertRaisesRegex(AssertionError, "escaped exact owned"):
            self.fixture.mutate_owned(target)
        self.assertEqual(target.read_bytes(), before)

    def test_fault_guard_rejects_alias_and_nonregular_or_multilink_before_write(self) -> None:
        """Fault safety itself is tested without creating a hardlink, socket or symlink."""
        target = Path(self.fixture.held.root) / "caption_pages.json"
        original = target.read_bytes()
        alias = target.parent / ".." / target.parent.name / target.name
        with self.assertRaisesRegex(AssertionError, "escaped exact owned"):
            self.fixture.mutate_owned(alias)
        values = ((stat.S_IFDIR | 0o700, 1), (stat.S_IFREG | 0o600, 2))
        for mode, links in values:
            info = SimpleNamespace(st_mode=mode, st_nlink=links)
            with patch.object(Path, "lstat", return_value=info), self.assertRaisesRegex(AssertionError, "regular single-link"):
                self.fixture.mutate_owned(target)
        self.assertEqual(target.read_bytes(), original)

    def test_input_changed_by_encode_rejects_before_copy(self) -> None:
        """The actual full input remains held across the native stub's return."""
        fixture, encode = self.fixture, self.fixture.encode

        def change(job: object) -> dict:
            """Change only fixture-owned in-memory input metadata."""
            result = encode(job)
            fixture.inputs.value["executionInputHash"] = "0" * 64
            return result

        fixture.encode = change
        with self.assertRaisesRegex(RuntimeError, "original metadata"):
            fixture.render_body()
        self.assertFalse((fixture.root / "picture-only.mp4").exists())

    def test_first_callback_cannot_establish_a_changed_input_baseline(self) -> None:
        """Hold exact original metadata before the very first owning callback."""
        fixture = self.fixture

        def change() -> None:
            """Only mutate a TEST input field during the first guard invocation."""
            fixture.guard()
            fixture.inputs.value["TEST-first-callback"] = "late"

        context = BodyPresenterCaptionContext(fixture.inputs, fixture.captions, fixture.owner, change)
        with self.assertRaisesRegex(RuntimeError, "original metadata"):
            prepare_presenter_caption_body(context, fixture.request, fixture.value,
                                           str(fixture.root / "picture-only.mp4"))
        self.assertEqual(fixture.commands, [])

    def test_numeric_only_input_drift_is_not_canonicalized_away(self) -> None:
        """Equal JSON numeric values retain their original runtime scalar types."""
        fixture, encode = self.fixture, self.fixture.encode
        fixture.inputs.value["TEST-number"] = 1

        def change(job: object) -> dict:
            """The held input must notice int-to-float after native return."""
            result = encode(job)
            fixture.inputs.value["TEST-number"] = 1.0
            return result

        fixture.encode = change
        with self.assertRaisesRegex(RuntimeError, "original metadata"):
            fixture.render_body()

    def test_actual_proof_is_held_before_phase_exit_callback(self) -> None:
        """An encode-phase wrapper cannot alter the already returned proof for retention."""
        fixture, phase = self.fixture, self.fixture.phase

        def change(name: str, operation: object) -> object:
            """Change only the mutable actual proof after its internal hold."""
            result = phase(name, operation)
            if name == "body-prefix-and-picture-encode":
                fixture.last_proof["elapsedMs"] = 4.0
            return result

        fixture.body.context.clock.phase = change
        with self.assertRaisesRegex(RuntimeError, "actual proof or output changed"):
            fixture.render_body()
        self.assertFalse((fixture.root / "picture-only.mp4").exists())

    def test_retained_bytes_held_before_phase_exit_callback(self) -> None:
        """Same-length post-copy substitution cannot mint a late stat beside old SHA."""
        fixture, phase = self.fixture, self.fixture.phase

        def change(name: str, operation: object) -> object:
            """Corrupt only the exact newly owned retained TEST picture."""
            result = phase(name, operation)
            if name == "body-retain-picture-copy":
                fixture.mutate_owned(fixture.root / "picture-only.mp4")
            return result

        fixture.body.context.clock.phase = change
        with self.assertRaisesRegex(RuntimeError, "retained picture changed"):
            fixture.render_body()
        self.assertIsNone(fixture.body.composition)

    def test_caption_completion_cannot_mutate_returned_proof(self) -> None:
        """The original actual proof stays unchanged through real caption completion."""
        fixture, complete = self.fixture, self.fixture.captions.complete

        def change(output: str, proof: dict) -> None:
            """Run original completion before a TEST-only result mutation."""
            complete(output, proof)
            proof["elapsedMs"] = 6.0

        with patch.object(fixture.captions, "complete", side_effect=change), \
                self.assertRaisesRegex(RuntimeError, "actual proof or output changed"):
            fixture.render_body()
        self.assertIsNone(fixture.body.composition)

    def test_final_verification_cannot_replace_caption_metadata(self) -> None:
        """Successful reinspection is not permission to change the original held pages."""
        fixture = self.fixture

        def change(context: object, report: dict, guard: object) -> None:
            """Alter metadata only after the genuine full-report recheck."""
            verify_presenter_caption_clearance(context, report, guard)
            context.held.data["TEST-late"] = True

        with patch("guided_presenter_caption_body_picture.verify_presenter_caption_clearance", side_effect=change), \
                self.assertRaisesRegex(RuntimeError, "original metadata"):
            fixture.render_body()
        self.assertIsNone(fixture.body.composition)

    def test_original_deadline_after_copy_cannot_be_renewed(self) -> None:
        """A complete prefix/copy cannot extend the caller's original work allowance."""
        fixture, phase = self.fixture, self.fixture.phase

        def expire(name: str, operation: object) -> object:
            """Expire the existing TEST clock after actual retained copy returns."""
            result = phase(name, operation)
            if name == "body-retain-picture-copy":
                fixture.probe.deadline.expired = True
            return result

        fixture.body.context.clock.phase = expire
        with self.assertRaisesRegex(RuntimeError, "expired"):
            fixture.render_body()
        self.assertIsNone(fixture.body.composition)

    def _last_caption_callback(self, change: object) -> None:
        """Arm only after actual pure binding; then fault the final original caption guard."""
        fixture, original = self.fixture, self.fixture.captions.guard
        armed = [False]

        def guard() -> None:
            """Keep the real original caption guard before the injected late callback."""
            original()
            if armed[0]:
                change()

        def project(report: dict, proof: dict, retained: dict, pages: tuple) -> dict:
            """Arm only after the unchanged projector returns actual bound TEST data."""
            result = body_presenter_caption_picture_record(report, proof, retained, pages)
            armed[0] = True
            return result

        fixture.captions.guard = guard
        with patch("guided_presenter_caption_body_picture.body_presenter_caption_picture_record", side_effect=project):
            fixture.render_body()

    def test_last_caption_callback_cannot_replace_presenter_deadline(self) -> None:
        """Reproduce the independent reviewer runtime replacement without a new clock."""
        runtime = self.fixture.owner.runtime
        original = runtime.deadline
        self.addCleanup(lambda: object.__setattr__(runtime, "deadline", original))
        replacement = SimpleNamespace(remaining=lambda: 999.0)
        with self.assertRaisesRegex(RuntimeError, "original owner/runtime/observation changed"):
            self._last_caption_callback(lambda: object.__setattr__(runtime, "deadline", replacement))
        self.assertIsNone(self.fixture.body.composition)

    def test_last_caption_callback_cannot_mutate_observed_geometry(self) -> None:
        """A changed actual observation cannot hide behind an unchanged compiled graph."""
        asset = self.fixture.owner.observed[0].graph_asset
        original = asset.width
        self.addCleanup(lambda: object.__setattr__(asset, "width", original))
        with self.assertRaisesRegex(RuntimeError, "original owner/runtime/observation changed"):
            self._last_caption_callback(lambda: object.__setattr__(asset, "width", original + 2))
        self.assertIsNone(self.fixture.body.composition)

    def test_last_caption_callback_cannot_expire_the_same_original_clock(self) -> None:
        """Clock identity alone is insufficient when its original allowance expires."""
        clock = self.fixture.probe.deadline
        self.addCleanup(lambda: setattr(clock, "expired", False))
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self._last_caption_callback(lambda: setattr(clock, "expired", True))
        self.assertIsNone(self.fixture.body.composition)

    def test_last_caption_callback_source_stat_change_is_rechecked_without_writing(self) -> None:
        """Only a synthetic stat changes; no presentation or dependency file is mutated."""
        target = Path(self.fixture.owner.observed[0].source.path)
        original = Path.lstat
        armed = [False]

        def observed(path: Path) -> object:
            """Return a distinct mtime only after the final caption callback completed."""
            info = original(path)
            if not armed[0] or path != target:
                return info
            keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            values = {key: getattr(info, key) for key in keys}
            values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)

        with patch.object(Path, "lstat", observed), self.assertRaisesRegex(RuntimeError, "original source/tool identity"):
            self._last_caption_callback(lambda: armed.__setitem__(0, True))
        self.assertIsNone(self.fixture.body.composition)


if __name__ == "__main__":
    unittest.main()
