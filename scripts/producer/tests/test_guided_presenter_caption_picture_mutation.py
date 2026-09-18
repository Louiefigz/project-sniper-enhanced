"""Late live caption/input/output substitutions must not publish bound clearance."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_presenter_caption_picture_fixture import CaptionPictureFixture
from guided_presenter_caption_clearance import inspect_presenter_caption_clearance, verify_presenter_caption_clearance
from guided_presenter_caption_picture import finish_presenter_caption_picture, prepare_presenter_caption_picture


class PresenterCaptionPictureMutationTests(unittest.TestCase):
    """TEST metadata fault injection only; no native work or isolated admission."""

    def setUp(self) -> None:
        """Keep a fresh original source clock and independent held files per case."""
        self.fixture = CaptionPictureFixture()
        self.addCleanup(self.fixture.close)

    def test_inspection_precedes_first_encode_and_verification_follows_last(self) -> None:
        """Recorded successful stubs cannot move the clearance gate after encoding."""
        fixture = self.fixture

        def before(context: object, guard: object) -> dict:
            """Capture actual preinspection order, not a mocked success result."""
            fixture.events.append("inspect")
            return inspect_presenter_caption_clearance(context, guard)

        def after(context: object, report: dict, guard: object) -> None:
            """Run the actual second inspection after both actual invocation stubs."""
            fixture.events.append("verify")
            verify_presenter_caption_clearance(context, report, guard)

        with patch("guided_presenter_caption_picture.inspect_presenter_caption_clearance", side_effect=before), \
                patch("guided_presenter_caption_picture.verify_presenter_caption_clearance", side_effect=after):
            fixture.render()
        self.assertEqual(fixture.events, ["inspect", "compose", "observe-picture", "compose", "observe-picture", "verify"])

    def test_input_mutation_after_first_encode_stops_second(self) -> None:
        """The full original execution input stays bound beyond the first inspector."""
        fixture = self.fixture
        original = fixture.compose

        def change(base: str, clips: list, path: str, options: object) -> int:
            """Mutate a non-graph original input after the encoder invocation."""
            result = original(base, clips, path, options)
            fixture.inputs.value["executionInputHash"] = "0" * 64
            return result

        fixture.compose = change
        with self.assertRaisesRegex(RuntimeError, "original inputs or clearance changed"):
            fixture.render()
        self.assertEqual(len(fixture.commands), 1)

    def test_actual_caption_file_change_after_first_encode_stops_second(self) -> None:
        """Current stat checks remain linked to the preinspection's actual byte read."""
        fixture = self.fixture
        original = fixture.compose

        def change(base: str, clips: list, path: str, options: object) -> int:
            """Replace actual held bytes without changing their in-memory reference."""
            result = original(base, clips, path, options)
            fixture.corrupt_owned_caption(Path(fixture.held.root) / "caption_pages.json")
            return result

        fixture.compose = change
        with self.assertRaisesRegex(RuntimeError, "original inputs or clearance changed"):
            fixture.render()
        self.assertEqual(len(fixture.commands), 1)

    def test_fault_helper_refuses_shared_dependencies_before_write(self) -> None:
        """External includes production code; never use array position as ownership."""
        target = Path(self.fixture.held.external[0].path)
        before = target.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "not an owned held caption file"):
            self.fixture.corrupt_owned_caption(target)
        self.assertEqual(target.read_bytes(), before)

    def test_fault_helper_refuses_parent_alias_without_changing_owned_file(self) -> None:
        """An existing fixture target still cannot be selected through dot-dot spelling."""
        target = Path(self.fixture.held.root) / "caption_pages.json"
        before = target.read_bytes()
        alias = target.parent / ".." / target.parent.name / target.name
        with self.assertRaisesRegex(RuntimeError, "not an owned held caption file"):
            self.fixture.corrupt_owned_caption(alias)
        self.assertEqual(target.read_bytes(), before)

    def test_fault_helper_refuses_nonregular_and_multiple_link_identity(self) -> None:
        """Stub identity faults only: no hard link, FIFO, socket or device is created."""
        target = Path(self.fixture.held.root) / "caption_pages.json"
        before = target.read_bytes()
        identities = (SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=2),
                      SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_nlink=1))
        for identity in identities:
            with patch.object(Path, "lstat", return_value=identity), \
                    self.assertRaisesRegex(RuntimeError, "single-link regular file"):
                self.fixture.corrupt_owned_caption(target)
        self.assertEqual(target.read_bytes(), before)

    def test_report_mutation_after_preinspection_cannot_be_resealed(self) -> None:
        """The original report object is retained, not regenerated after a change."""
        fixture = self.fixture
        reports = []
        original = fixture.compose

        def capture(context: object, guard: object) -> dict:
            """Retain exactly the report returned by the existing live inspector."""
            result = inspect_presenter_caption_clearance(context, guard)
            reports.append(result)
            return result

        def change(base: str, clips: list, path: str, options: object) -> int:
            """Change an otherwise successful report during actual invocation."""
            result = original(base, clips, path, options)
            reports[0]["state"] = "not-applicable"
            return result

        fixture.compose = change
        with patch("guided_presenter_caption_picture.inspect_presenter_caption_clearance", side_effect=capture), \
                self.assertRaisesRegex(RuntimeError, "original inputs or clearance changed"):
            fixture.render()
        self.assertEqual(len(fixture.commands), 1)

    def test_changed_held_data_after_final_inspection_is_still_rejected(self) -> None:
        """A final owner callback cannot replace verified captions with new metadata."""
        fixture = self.fixture

        def change(context: object, report: dict, guard: object) -> None:
            """Mutate only after genuine post-composition verification succeeded."""
            verify_presenter_caption_clearance(context, report, guard)
            context.held.data["TEST-late"] = True

        with patch("guided_presenter_caption_picture.verify_presenter_caption_clearance", side_effect=change), \
                self.assertRaisesRegex(RuntimeError, "original inputs or clearance changed"):
            fixture.render()
        self.assertEqual(len(fixture.commands), 2)

    def test_expiry_after_last_picture_does_not_return_earlier_clearance(self) -> None:
        """A completed picture cannot extend the originally supplied owner deadline."""
        fixture = self.fixture
        original = fixture.observed_picture

        def expire(path: Path, expected: tuple, tools: dict) -> dict:
            """Expire only after the final actual output observation stub."""
            result = original(path, expected, tools)
            if expected[1] == 120:
                fixture.probe.deadline.expired = True
            return result

        fixture.observed_picture = expire
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            fixture.render()
        self.assertEqual(len(fixture.commands), 2)

    def test_final_picture_mutation_during_callback_cannot_attach_original_report(self) -> None:
        """The late bound range records themselves must survive all final callbacks."""
        fixture = self.fixture
        pictures = fixture.render()
        prepared = prepare_presenter_caption_picture(fixture.presenter, fixture.held, fixture.authority)
        original = deepcopy(pictures)
        calls = []

        def guard() -> None:
            """Mutate at the second finalization callback, after strong reinspection."""
            calls.append(True)
            if len(calls) == 2:
                pictures["ranges"]["review"]["sha256"] = "0" * 64

        with self.assertRaisesRegex(RuntimeError, "does not bind|picture evidence changed"):
            finish_presenter_caption_picture(prepared, pictures, guard)
        self.assertNotEqual(pictures, original)


if __name__ == "__main__":
    unittest.main()
