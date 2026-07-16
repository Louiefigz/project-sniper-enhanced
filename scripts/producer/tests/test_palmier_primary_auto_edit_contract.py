"""Palmier-primary Auto Edit authority contracts (offline; no live MCP)."""
from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.checkpoint import Authority, _checkpoint_state
from palmier.checkpoint_plan import prepare_checkpoint_plan
from palmier.native_qc_export import export_candidate
from palmier.timeline_authority import TimelineSnapshot, record_authority


def _snapshot(timeline_id: str) -> TimelineSnapshot:
    timeline = {
        "id": timeline_id,
        "name": "Editable working head",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "totalFrames": 60,
        "tracks": [],
    }
    return TimelineSnapshot(
        project_id="project-1",
        timeline_id=timeline_id,
        fingerprint=timeline_id[0] * 64,
        semantic_fingerprint=timeline_id[-1] * 64,
        timeline=timeline,
        coverage={"complete": True},
    )


class PrimaryLineageContractTests(unittest.TestCase):
    def test_revision_records_an_explicit_working_head_successor(self) -> None:
        """A revision may fork, but its parent and promoted head stay unambiguous."""
        with tempfile.TemporaryDirectory() as out_dir:
            parent = _snapshot("parent-1")
            successor = _snapshot("successor-2")
            record_authority(out_dir, successor, "sniper-bootstrap", {
                "projectId": parent.project_id,
                "timelineId": parent.timeline_id,
                "fingerprint": parent.fingerprint,
            })
            session = SimpleNamespace(
                target=SimpleNamespace(
                    project_id="project-1", name="demo", path="/demo.palmier"),
                build_id="successor-2",
                request=SimpleNamespace(
                    out_dir=out_dir,
                    parity={"stage": "revision", "round": 2}),
                lanes={"project": {"fps": 30, "width": 1920, "height": 1080}},
            )
            saved = _checkpoint_state(
                {"timelineIds": [{"id": "parent-1", "name": "parent"}]},
                session,
                SimpleNamespace(media_map={}),
                Authority("p" * 64, "m" * 64, None, "k" * 64),
                "Sniper revision 2",
                {"mode": "native-primary", "approved": False},
                {"ok": True, "timelineId": "successor-2"},
                {
                    "projectId": "project-1",
                    "timelineId": "parent-1",
                    "fingerprint": parent.fingerprint,
                },
                [{"id": "successor-2"}, {"id": "parent-1"}],
            )

            checkpoint = saved["workingCheckpoint"]
            self.assertEqual(saved["latestTimelineId"], "successor-2")
            self.assertEqual(checkpoint["parent"]["timelineId"], "parent-1")
            self.assertEqual(checkpoint["readback"]["timelineId"], "successor-2")

    def test_material_omissions_are_named_by_lane(self) -> None:
        """Unsupported b-roll/music may block later, but may never disappear."""
        prepared = prepare_checkpoint_plan({
            "target": {"mode": "longform"},
            "cutTrack": [{"sourceId": "src", "start": 0, "end": 2}],
            "brollTrack": [{"sourceId": "broll", "outStart": 0, "outEnd": 1}],
            "music": {"enabled": True, "sourceId": "bed"},
        }, render_graphics=False)

        omissions = {row["lane"]: row for row in prepared.omissions}
        self.assertIn("broll", omissions)
        self.assertIn("music", omissions)
        self.assertNotIn("brollTrack", prepared.plan)
        self.assertNotIn("music", prepared.plan)


class PrimaryQcContractTests(unittest.TestCase):
    def test_qc_exports_the_explicit_editable_timeline_id(self) -> None:
        """QC cannot depend on whichever Palmier timeline happens to be active."""
        with tempfile.TemporaryDirectory() as out_dir:
            calls: list[tuple[str, dict]] = []

            def call(tool: str, arguments: dict) -> str:
                calls.append((tool, arguments))
                with open(arguments["outputPath"], "wb") as handle:
                    handle.write(b"editable-timeline-export")
                return "started"

            client = SimpleNamespace(call=call)
            candidate = _snapshot("editable-head-9")
            media = {"streams": [
                {"codec_type": "video"},
                {"codec_type": "audio"},
            ]}
            probe = SimpleNamespace(duration_s=2.0, frame_error=0.0)
            with patch("palmier.native_qc_export.wait_for_export"), \
                    patch("palmier.native_qc_export.verify_export",
                          return_value=probe), \
                    patch("palmier.native_qc_export.ffprobe_json",
                          return_value=media):
                result = export_candidate(client, out_dir, candidate)

            self.assertEqual(calls[0][0], "export_project")
            self.assertEqual(calls[0][1]["timelineId"], "editable-head-9")
            self.assertEqual(result["timelineId"], "editable-head-9")
            self.assertTrue(result["audioPresent"])


if __name__ == "__main__":
    unittest.main()
