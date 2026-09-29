"""Shared role-packet TEST fixture: a private root whose budget authority and work-lease state are never the user's.

Fixtures are TEST-labelled synthetic plans; no packet here grants or implies any review.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import native_work_lease
from studio import native_budget_store


def sha(path: Path) -> str:
    """Hash one fixture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RolePacketFixture(unittest.TestCase):
    """Disposable canonical directory with a small TEST native plan."""

    def setUp(self) -> None:
        """A private root; the budget authority and work-lease state live under it, never the user's."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for module, name in ((native_budget_store, "default_root"), (native_work_lease, "state_root")):
            self.enterContext(patch.object(module, name, return_value=self.root / name))

    def write(self, name: str, content: str | dict) -> Path:
        """Write a fixture file, JSON-encoding dictionaries."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) if isinstance(content, dict) else content)
        return path

    def plan(self, extra: dict | None = None) -> Path:
        """A TEST native plan with a request packet, a catalog file, an asset and a prior review."""
        request = self.write("requests/abc/SHORT-REQUEST.json", {"schemaVersion": 1, "scope": "TEST"})
        self.write("requests/abc/AGENT-BRIEF.md", "TEST brief")
        catalog = self.write("catalog/title.html", "<div>TEST</div>")
        asset = self.write("assets/font.ttf", "TEST font bytes")
        review = self.write("clip/PREBUILD-REVIEW-v1.json", {"planHash": "0" * 64, "review": {"verdict": "pass"},
                            "reviewer": {"sessionId": "TEST-old-critic", "plannerSessionId": "TEST-author"}})
        value = {"schemaVersion": 1, "canvas": {"frameRate": "30/1", "totalFrames": 90, "title": "TEST"},
                 "strategy": {"scenes": [{"startFrame": 0, "endFrame": 60, "format": "presenter"},
                                         {"startFrame": 60, "endFrame": 90, "format": "diagram"}]},
                 "assets": [{"path": str(asset), "sha256": sha(asset), "file": "assets/font.ttf", "role": "runtime"}],
                 "catalogFiles": [{"path": str(catalog), "sha256": sha(catalog), "file": "compositions/title.html",
                                   "catalogId": "TEST-title"}],
                 "requestPacket": {"path": str(request), "sha256": sha(request)},
                 "prebuildReview": {"path": str(review), "sha256": sha(review)}, **(extra or {})}
        return self.write("clip/native-plan-v2.json", value)
