#!/usr/bin/env python3
"""Transactional publication tests for qualified plan rebinding."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qualification_plan_rebind_publish import RebindPublication, publish_bundle


class RebindPublicationTests(unittest.TestCase):
    def test_support_evidence_precedes_authoritative_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = root / "plan.json"
            proposal = root / "proposal.json"
            report = root / "report.json"
            linked = []
            real_link = os.link

            def recording_link(source, destination, **kwargs):
                linked.append(Path(destination).name)
                return real_link(source, destination, **kwargs)

            with patch(
                "qualification_plan_rebind_publish.os.link",
                side_effect=recording_link,
            ):
                result = publish_bundle(
                    RebindPublication(
                        plan,
                        {"cutTrack": []},
                        proposal,
                        {"introSemanticBeats": []},
                        report,
                        {"ok": True},
                    )
                )
            self.assertEqual(linked, ["proposal.json", "report.json", "plan.json"])
            self.assertTrue(result["publication"]["authoritativePlanPublishedLast"])
            self.assertEqual(json.loads(report.read_text()), result)

    def test_link_failure_rolls_back_every_owned_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            real_link = os.link
            calls = 0

            def failing_link(source, destination, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected publication failure")
                return real_link(source, destination, **kwargs)

            paths = [root / name for name in ("plan.json", "proposal.json", "report.json")]
            with patch(
                "qualification_plan_rebind_publish.os.link",
                side_effect=failing_link,
            ), self.assertRaisesRegex(OSError, "injected"):
                publish_bundle(
                    RebindPublication(
                        paths[0], {}, paths[1], {}, paths[2], {"ok": True}
                    )
                )
            self.assertFalse(any(path.exists() for path in paths))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_existing_or_aliased_outputs_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            existing = root / "plan.json"
            existing.write_text("operator-owned")
            with self.assertRaisesRegex(RuntimeError, "new JSON"):
                publish_bundle(
                    RebindPublication(
                        existing,
                        {},
                        root / "proposal.json",
                        {},
                        root / "report.json",
                        {"ok": True},
                    )
                )
            self.assertEqual(existing.read_text(), "operator-owned")
            with self.assertRaisesRegex(RuntimeError, "distinct"):
                publish_bundle(
                    RebindPublication(
                        root / "same.json",
                        {},
                        root / "same.json",
                        {},
                        root / "other.json",
                        {"ok": True},
                    )
                )


if __name__ == "__main__":
    unittest.main()
