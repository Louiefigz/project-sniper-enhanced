"""Cold-body TEST records over real tiny held captions; pictures/prefix are stubs."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from _guided_presenter_body_read_fixture import comparison_records, oracle_test_metadata
from _presenter_caption_read_fixture import CaptionReadFixture
from guided_caption_layers import caption_page_clips, caption_prefix_request
from guided_presenter_body_read import PresenterBodyReadContext, _graph
from guided_presenter_caption_body_record import body_presenter_caption_picture_record
from guided_presenter_caption_clearance import inspect_presenter_caption_clearance
from guided_presenter_read import read_presenter_graphs
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixRanges, canonical_hash
from test_opening_prefix_contract import held


class CaptionBodyReadFixture:
    """No renderer, source admission, decoded body or actual creator approval."""

    def __init__(self, span: tuple[int, int] = (0, 120)) -> None:
        """Build the full page graph and independently held TEST output/tool bytes."""
        self.original = CaptionReadFixture(span)
        item = self.original
        authority = item.inputs.documents["authority"]
        clock = PrefixClock(authority["frameRate"], authority["totalFrames"], 1080, 1920)
        ranges = PrefixRanges(*tuple((authority[key]["startFrame"], authority[key]["endFrameExclusive"])
                                     for key in ("core", "review")))
        self.request = caption_prefix_request(CompositorPrefixRequest(item.base, (), (), (), clock, ranges), item.held)
        tool_path = item.fixture.root / "TEST-ffmpeg-not-executed"
        tool_path.write_bytes(b"TEST distinct held tool, never executed")
        self.context = PresenterBodyReadContext(item.read, item.pictures,
            (held(tool_path), held(Path(item.read.ffprobe.path))))
        with item.selected():
            evidence = read_presenter_graphs(item.pictures["presenterLayers"]["observations"], item.read)
        self.proof = self._proof(evidence)
        self.composition = self._composition()

    def _proof(self, evidence: object) -> dict:
        """Match the exact original proof schema with explicitly invented pixel attestations."""
        request = self.request
        oracle = {**oracle_test_metadata(), "schemaVersion": 2, "kind": "presenter-compositor-prefix-oracle", "status": "verified",
            "clock": asdict(request.clock), "fullGraphHash": canonical_hash(_graph(request, evidence, "full")),
            "openingGraphHash": canonical_hash(_graph(request, evidence, "opening")),
            "inputs": [asdict(request.base), *[asdict(row) for row in request.assets], *list(evidence.assets),
                       *[asdict(row) for row in self.context.tools]],
            "presenterObservations": self.original.pictures["presenterLayers"]["observations"],
            "comparison": comparison_records(request),
            "layerPolicy": {"kind": "held-presenter-then-graphics-then-caption-pages-v1",
                "fullPresenterWindows": len(evidence.full["windows"]),
                "openingPresenterWindows": len(evidence.opening["windows"]) if evidence.opening else 0,
                "fullCaptionTail": request.caption_tail[0], "openingCaptionTail": request.caption_tail[1]},
            "encodedOutputObserved": False, "audioCompared": False, "approvalObserved": False}
        directory = self.original.fixture.root / "body-candidate"
        directory.mkdir(mode=0o700)
        output = directory / "final.mp4"
        output.write_bytes(b"TEST body bytes, no actual prefix or picture decode")
        return {"schemaVersion": 2, "kind": "verified-presenter-prefix-private-picture-composition",
            "scope": "executed-graph-bound-picture-not-decoded-output-or-approval", "outputPath": str(output),
            "output": asdict(held(output)), "executedCommandHash": "5" * 64, "ordinaryPathCommandHash": "6" * 64,
            "outputTransport": "exclusively-reserved-held-regular-file-descriptor-mp4",
            "privateMoovPlacement": "end-of-file; faststart belongs to existing final delivery mux",
            "prefixOracle": oracle, "elapsedMs": 1.0, "outputDecoded": False, "audioCompared": False,
            "deliveryApproved": False, "cleanupScope": "owned-runner-local-groups; caller-must-reconcile-external-ledger"}

    def _composition(self) -> dict:
        """Derive the real full manual-clearance report, without claiming encoded pixels."""
        item = self.original
        context = replace(item.fixture.context, inputs=item.inputs,
            coverage={"startFrame": 0, "endFrameExclusive": self.request.clock.total_frames})
        report = inspect_presenter_caption_clearance(context, item.fixture.guard)
        output = self.proof["output"]
        retained_path = item.fixture.root / "picture-only.mp4"
        retained_path.write_bytes(Path(output["path"]).read_bytes())
        retained = held(retained_path)
        reference = {"path": retained.path, "sha256": retained.sha256, "sizeBytes": retained.size_bytes}
        return {**self.proof, "retainedPicture": reference,
            "originalGraphDerivation": {"TEST": "caller authenticates actual original derivation separately"},
            "presenterCaptionClearance": body_presenter_caption_picture_record(report, self.proof, reference,
                caption_page_clips(item.held))}

    def close(self) -> None:
        """Dispose only of this fixture's exact original temporary directories."""
        self.original.close()

    @contextmanager
    def selected(self) -> Iterator[None]:
        """Stub only original V8 selection, not graph/cue/file/readback logic."""
        with self.original.selected(), patch("guided_presenter_caption_body_read.capture_selection",
                                             return_value=self.original.selection):
            yield
