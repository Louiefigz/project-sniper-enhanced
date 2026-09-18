"""Deterministic qualified-media plan rebinding tests."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest_admission_contract import canonical_bytes
from qualification_plan_rebind import (
    RebindError,
    _expected_intent,
    _match_beats,
    _rebind_graphics,
)
from qualification_plan_rebind_inputs import (
    RebindAuthorityPaths,
    global_visual_state,
    qualification_errors,
    select_source,
    verify_authorities,
)

def _beat(beat_id: str, start: float, evidence: str = "three exact things") -> dict:
    return {
        "beatId": beat_id,
        "shape": "list",
        "trigger": "enumeration",
        "outStart": start,
        "outEnd": start + 0.8,
        "evidence": evidence,
    }


def _proposal(*beats: dict) -> dict:
    return {"introSemanticBeats": list(beats)}


def _plan() -> dict:
    return {
        "graphicsTrack": [
            {
                "id": "graphic-1",
                "semanticBeatId": "old-beat",
                "outStart": 3.0,
                "outEnd": 5.5,
            }
        ],
        "graphicsDecisions": [
            {
                "beatId": "old-beat",
                "graphicId": "graphic-1",
                "decision": "graphic",
            }
        ],
    }


def _qualification(source: Path) -> tuple[dict, dict]:
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    evidence = {
        "schemaVersion": 1,
        "policy": "sniper-overcap-qualification-mezzanine-v1",
        "target": {"rate": "24/1", "width": 1920, "height": 1080},
        "output": {
            "sha256": digest,
            "sizeBytes": len(payload),
            "streamFacts": {"durationSeconds": 12.0},
        },
    }
    unsigned = dict(evidence)
    evidence["evidenceDigest"] = hashlib.sha256(
        b"sniper-overcap-qualification-mezzanine-v1\0" + canonical_bytes(unsigned)
    ).hexdigest()
    manifest_source = {
        "id": "fresh-primary",
        "role": "primary",
        "path": str(source),
        "sourceSha256": digest,
        "sourceSizeBytes": len(payload),
        "fps": 24.0,
        "frameRate": "24/1",
        "resolution": [1920, 1080],
        "duration": 12.0,
        "transcriptPath": "fresh.transcript.json",
    }
    return evidence, manifest_source


class QualificationPlanRebindTests(unittest.TestCase):
    def test_unique_semantic_match_updates_ids_and_preserves_hold(self) -> None:
        matches = _match_beats(
            _proposal(_beat("old-beat", 2.0)), _proposal(_beat("fresh-beat", 2.125))
        )
        plan = _plan()
        shifts = _rebind_graphics(plan, matches)
        graphic = plan["graphicsTrack"][0]
        self.assertEqual(graphic["semanticBeatId"], "fresh-beat")
        self.assertEqual(plan["graphicsDecisions"][0]["beatId"], "fresh-beat")
        self.assertEqual((graphic["outStart"], graphic["outEnd"]), (3.125, 5.625))
        self.assertEqual(graphic["outEnd"] - graphic["outStart"], 2.5)
        self.assertEqual(shifts[0]["deltaSeconds"], 0.125)

    def test_punctuation_only_change_is_same_exact_token_evidence(self) -> None:
        matches = _match_beats(
            _proposal(_beat("old", 1.0, "Three exact things.")),
            _proposal(_beat("new", 1.0, "three, exact things")),
        )
        self.assertEqual(matches["old"]["fresh"]["beatId"], "new")

    def test_added_or_missing_semantic_beat_fails_closed(self) -> None:
        previous = _proposal(_beat("old", 1.0))
        fresh = _proposal(_beat("new", 1.0), _beat("extra", 4.0, "five tools"))
        with self.assertRaisesRegex(RebindError, "beat set changed") as caught:
            _match_beats(previous, fresh)
        self.assertEqual(len(caught.exception.details["added"]), 1)

    def test_duplicate_semantic_signature_is_ambiguous(self) -> None:
        duplicate = _proposal(_beat("a", 1.0), _beat("b", 2.0))
        with self.assertRaisesRegex(RebindError, "ambiguous"):
            _match_beats(duplicate, _proposal(_beat("fresh", 1.0)))

    def test_semantic_reorder_fails_closed(self) -> None:
        previous = _proposal(
            _beat("old-a", 1.0, "first unique thing"),
            _beat("old-b", 2.0, "second unique thing"),
        )
        fresh = _proposal(
            _beat("new-b", 1.0, "second unique thing"),
            _beat("new-a", 2.0, "first unique thing"),
        )
        with self.assertRaisesRegex(RebindError, "order changed"):
            _match_beats(previous, fresh)

    def test_duplicate_graphic_decision_fails_closed(self) -> None:
        matches = _match_beats(
            _proposal(_beat("old-beat", 2.0)),
            _proposal(_beat("fresh-beat", 2.1)),
        )
        plan = _plan()
        plan["graphicsDecisions"].append(dict(plan["graphicsDecisions"][0]))
        with self.assertRaisesRegex(RebindError, "binding is incomplete"):
            _rebind_graphics(plan, matches)

    def test_source_selection_never_guesses_between_primary_sources(self) -> None:
        manifest = {
            "sources": [
                {"id": "a", "role": "primary", "transcriptPath": "a.json"},
                {"id": "b", "role": "primary", "transcriptPath": "b.json"},
            ]
        }
        with self.assertRaisesRegex(RebindError, "ambiguous"):
            select_source(manifest, None)
        self.assertEqual(select_source(manifest, "b")["id"], "b")

    def test_qualification_binds_hash_size_cadence_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "qualified.mp4"
            source.write_bytes(b"qualified-media")
            evidence, manifest_source = _qualification(source)
            self.assertEqual(qualification_errors(evidence, manifest_source), [])
            evidence["output"]["sha256"] = "0" * 64
            errors = qualification_errors(evidence, manifest_source)
            self.assertIn("qualification evidence digest is invalid", errors)
            self.assertIn(
                "manifest source SHA-256 differs from qualified output", errors
            )

    def test_exact_production_authorities_are_all_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "qualified.mp4"
            source.write_bytes(b"qualified-media")
            qualification, manifest_source = _qualification(source)
            cadence = {
                "approvalDigest": "a" * 64,
                "qualification": {
                    "evidencePath": str(root / "qualification.json"),
                    "evidenceDigest": qualification["evidenceDigest"],
                },
                "media": {"normalized": qualification["output"]},
                "downstreamTimeAuthority": {
                    "mediaSha256": qualification["output"]["sha256"],
                    "transcriptAndCutsMustBindThisAsset": True,
                    "rawSourceIsNotEditTimeAuthority": True,
                },
            }
            with patch(
                "qualification_plan_rebind_inputs.verify_qualification_evidence",
                return_value=qualification,
            ) as verify_qualification, patch(
                "qualification_plan_rebind_inputs.verify_execution_media_authority",
                return_value=True,
            ) as verify_admission, patch(
                "qualification_plan_rebind_inputs.verify_cadence_approval",
                return_value=cadence,
            ) as verify_cadence:
                observed = verify_authorities(
                    {},
                    {"sources": [manifest_source]},
                    RebindAuthorityPaths(
                        root / "asset_manifest.json",
                        root / "qualification.json",
                        root / "cadence.json",
                    ),
                    manifest_source,
                )
            self.assertEqual(observed, (qualification, cadence))
            verify_qualification.assert_called_once()
            verify_admission.assert_called_once()
            verify_cadence.assert_called_once()

    def test_visual_state_rejects_non_finite_or_out_of_canvas_bbox(self) -> None:
        for bbox in ([float("nan"), 0.1, 0.2, 0.2], [0.9, 0.1, 0.2, 0.2]):
            with self.subTest(bbox=bbox), patch(
                "qualification_plan_rebind_inputs.verify_visual_state",
                return_value={
                    "measurement": {
                        "rows": [
                            {
                                "outStart": 0,
                                "outEnd": 12,
                                "state": "talking-head",
                                "faceBBoxNorm": bbox,
                            }
                        ]
                    }
                },
            ):
                with self.assertRaisesRegex(RebindError, "valid state"):
                    global_visual_state(Path("/unused/receipt.json"))

    def test_expected_intent_must_be_fresh_project_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            source.mkdir()
            manifest = source / "asset_manifest.json"
            project = root / "project.json"
            project.write_text(
                '{"resolvedIntent":{"mode":"longform","scope":"produced"}}'
            )
            self.assertEqual(
                _expected_intent(project, manifest)["mode"], "longform"
            )
            copied = root / "copied-intent.json"
            copied.write_bytes(project.read_bytes())
            with self.assertRaisesRegex(RebindError, "fresh project"):
                _expected_intent(copied, manifest)

    def test_visual_state_must_bind_selected_source_and_duration(self) -> None:
        receipt = {
            "source": {
                "path": "/admitted/qualified.mp4",
                "sha256": "a" * 64,
                "sizeBytes": 20,
            },
            "measurement": {
                "rows": [
                    {
                        "outStart": 0,
                        "outEnd": 12,
                        "state": "talking-head",
                        "faceBBoxNorm": [0.4, 0.2, 0.2, 0.3],
                    }
                ]
            },
        }
        source = {
            "path": "/admitted/qualified.mp4",
            "sourceSha256": "a" * 64,
            "sourceSizeBytes": 20,
            "duration": 12,
        }
        with patch(
            "qualification_plan_rebind_inputs.verify_visual_state",
            return_value=receipt,
        ):
            self.assertEqual(
                global_visual_state(Path("/unused/receipt.json"), source)[
                    "state"
                ],
                "talking-head",
            )
            changed = dict(source, sourceSha256="b" * 64)
            with self.assertRaisesRegex(RebindError, "selected admitted"):
                global_visual_state(Path("/unused/receipt.json"), changed)
            changed = dict(source, duration=13)
            with self.assertRaisesRegex(RebindError, "valid state"):
                global_visual_state(Path("/unused/receipt.json"), changed)


if __name__ == "__main__":
    unittest.main()
