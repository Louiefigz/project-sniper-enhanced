"""Actual original-caption cold read at body preparation; no native media or admission."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from _presenter_caption_read_fixture import CaptionReadFixture
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition
from guided_body_prefix import BodyPrefixBinding
from guided_presenter_body_prefix import presenter_body_prefix
from guided_presenter_caption_read import verify_presenter_caption_picture
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixRanges


class PresenterCaptionBodyPrefixTests(unittest.TestCase):
    """Read the original bound opening before attaching its separately held live body owner."""

    def setUp(self) -> None:
        """Reuse real TEST caption files and explicit source-selection/probe leaves."""
        self.fixture = CaptionReadFixture()
        self.addCleanup(self.fixture.close)
        fixture = self.fixture
        owner = fixture.fixture.owner
        clock = PrefixClock("30/1", 960, 1080, 1920)
        self.request = CompositorPrefixRequest(fixture.base, (), (), (), clock,
                                               PrefixRanges((0, 60), (0, 120)))
        self.binding = BodyPrefixBinding(fixture.inputs, {"pictures": fixture.pictures},
                                        fixture.fixture.root, fixture.held)
        self.value = GraphicsComposition(fixture.base.path, str(fixture.fixture.root / "TEST-not-rendered"), (),
            CompositeOptions(eof_pass=True, video_only=True, frame_rate="30/1", presenter=owner.full_graph()),
            (1080, 1920), ("30/1", 960), presenter=owner)

    def test_original_caption_binding_is_read_once_before_live_graph_attachment(self) -> None:
        """The caption verifier already includes the original graph read; no direct duplicate."""
        with self.fixture.selected(), \
                patch("guided_presenter_caption_read.verify_presenter_caption_picture",
                      wraps=verify_presenter_caption_picture) as reader, \
                patch("guided_presenter_read.verify_opening_presenter_layers") as direct:
            result = presenter_body_prefix(self.request, self.value, self.binding)
        reader.assert_called_once()
        direct.assert_not_called()
        self.assertIsNone(self.request.presenter)
        self.assertIs(result.presenter.observations, self.fixture.fixture.owner.observed)
        self.assertEqual(reader.call_args.args[3], self.fixture.layers)

    def test_missing_opening_caption_clearance_cannot_use_direct_graph_success(self) -> None:
        """A genuine graph receipt alone is insufficient for the captioned body branch."""
        self.fixture.pictures.pop("presenterCaptionClearance")
        with self.fixture.selected(), self.assertRaises(RuntimeError):
            presenter_body_prefix(self.request, self.value, self.binding)

    def test_original_opening_cannot_change_its_caption_projection_binding(self) -> None:
        """No body live owner can repair or replace the original read-side caption report."""
        self.fixture.pictures["presenterCaptionClearance"]["captionProjectionHash"] = "0" * 64
        with self.fixture.selected(), self.assertRaises(RuntimeError):
            presenter_body_prefix(self.request, self.value, self.binding)

    def test_cold_opening_clips_are_independently_derived_from_original_pages(self) -> None:
        """A changed caption tail cannot silently pass through a presenter-only read."""
        original = deepcopy(self.fixture.pictures["captionLayers"])
        self.fixture.pictures["captionLayers"]["captionTail"] += 1
        with self.fixture.selected(), self.assertRaises(RuntimeError):
            presenter_body_prefix(self.request, self.value, self.binding)
        self.assertNotEqual(self.fixture.pictures["captionLayers"], original)


if __name__ == "__main__":
    unittest.main()
