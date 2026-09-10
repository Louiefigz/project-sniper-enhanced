"""Offline project-isolation contracts for connected Palmier acceptance."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _common import *  # noqa: F401,F403
from palmier.live_acceptance_project_safety import (
    capture_prior, fingerprint_protected_project, project_surface,
    require_same_protected_project, restore_project,
    validate_protected_path,
)
from palmier.live_acceptance_cleanup import cleanup_cohort
from palmier.mcp_client import PalmierError


class ProjectClient:
    """Small stateful client exposing only project lifecycle/read calls."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    def _payload(self) -> dict:
        return {
            "openCount": sum(
                row.get("isOpen") is True for row in self.rows),
            "projects": self.rows,
        }

    def call_json(self, tool: str, args: dict) -> dict:
        if tool == "get_projects":
            return self._payload()
        if tool == "open_project":
            self.call(tool, args)
            return next(
                row for row in self.rows if row["path"] == args["path"])
        raise AssertionError(tool)

    def call(self, tool: str, args: dict) -> str:
        self.calls.append((tool, args))
        target = next(
            row for row in self.rows if row["path"] == args["path"])
        if tool == "open_project":
            for row in self.rows:
                row["isActive"] = False
            target.update({"isOpen": True, "isActive": True})
        elif tool == "close_project":
            target.update({"isOpen": False, "isActive": False})
        else:
            raise AssertionError(tool)
        return "{}"


def _row(path: str, opened: bool = False) -> dict:
    return {
        "id": "protected-id", "name": Path(path).stem, "path": path,
        "isAccessible": True, "isOpen": opened, "isActive": opened,
    }


class ProjectSafetyTests(unittest.TestCase):
    def test_open_count_and_active_flags_must_be_coherent(self):
        row = _row("/tmp/Protected.palmier")
        with self.assertRaisesRegex(PalmierError, "openCount"):
            project_surface({"openCount": 1, "projects": [row]})
        row.update({"isActive": True, "isOpen": False})
        with self.assertRaisesRegex(PalmierError, "openCount"):
            project_surface({"openCount": 0, "projects": [row]})

    def test_capture_prior_records_exact_zero_open_surface(self):
        client = ProjectClient([_row("/tmp/Protected.palmier")])
        prior = capture_prior(client)
        self.assertEqual(
            prior["surface"], {"openCount": 0, "openProjects": []})
        self.assertEqual(
            prior["knownProjectPaths"], ["/tmp/Protected.palmier"])

    @patch("palmier.live_acceptance_project_safety.read_active")
    def test_protected_fingerprint_uses_only_open_read_close(
            self, read_active):
        path = "/tmp/Protected.palmier"
        client = ProjectClient([_row(path)])
        read_active.return_value = SimpleNamespace(
            timeline_id="timeline", fingerprint="exact",
            semantic_fingerprint="semantic",
            coverage={"complete": True},
        )
        empty = {"openCount": 0, "openProjects": []}
        proof = fingerprint_protected_project(client, path, empty)
        self.assertEqual(
            [tool for tool, _args in client.calls],
            ["open_project", "close_project"])
        self.assertEqual(proof["timelineContentMutationsIssued"], 0)
        self.assertEqual(project_surface(client._payload()), empty)
        require_same_protected_project(proof, dict(proof))

    def test_restore_rejects_inactive_but_still_open_disposable(self):
        path = "/tmp/Disposable.palmier"

        class BrokenClose(ProjectClient):
            def call(self, tool: str, args: dict) -> str:
                if tool == "close_project":
                    self.calls.append((tool, args))
                    self.rows[0]["isActive"] = False
                    return "{}"
                return super().call(tool, args)

        client = BrokenClose([_row(path, True)])
        prior = {
            "project": None, "timelineId": None, "fingerprint": None,
            "surface": {"openCount": 0, "openProjects": []},
        }
        with self.assertRaisesRegex(PalmierError, "surface"):
            restore_project(
                client, prior, {"id": "protected-id", "path": path})

    def test_restore_closes_disposable_to_exact_zero_open_surface(self):
        path = "/tmp/Disposable.palmier"
        client = ProjectClient([_row(path, True)])
        prior = {
            "project": None, "timelineId": None, "fingerprint": None,
            "surface": {"openCount": 0, "openProjects": []},
        }
        proof = restore_project(
            client, prior, {"id": "protected-id", "path": path})
        self.assertEqual(
            proof["openState"], {"openCount": 0, "openProjects": []})

    def test_protected_path_requires_real_absolute_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp, "Protected.palmier")
            bundle.mkdir()
            self.assertEqual(
                validate_protected_path(str(bundle)), str(bundle))
            with self.assertRaisesRegex(PalmierError, "regular bundle"):
                validate_protected_path("Protected.palmier")

    def test_failed_restoration_retains_disposable_for_recovery(self):
        evidence = SimpleNamespace(
            value={
                "config": {"protected_project_path": None},
                "phases": {}, "cleanup": {},
                "cleanupPolicy": {"trashDisposable": True},
            },
            save=Mock(),
        )
        project = {
            "id": "disposable", "name": "Sniper Test",
            "path": "/tmp/Sniper Test.palmier",
        }
        with patch(
                "palmier.live_acceptance_cleanup.restore_project",
                side_effect=PalmierError("restore mismatch")), patch(
                    "palmier.live_acceptance_cleanup._fallback_restore"), patch(
                        "palmier.live_acceptance_cleanup._restore_local"), patch(
                            "palmier.live_acceptance_cleanup.trash_disposable"
                        ) as trash:
            errors = cleanup_cohort(
                Mock(), evidence, {"project": None}, project)
        self.assertTrue(any("restore mismatch" in row for row in errors))
        trash.assert_not_called()
        self.assertEqual(
            evidence.value["cleanup"]["retainedForReview"], project["path"])

    def test_cleanup_policy_false_never_trashes_successfully_restored_bundle(self):
        evidence = SimpleNamespace(
            value={
                "config": {"protected_project_path": None},
                "phases": {}, "cleanup": {},
                "cleanupPolicy": {"trashDisposable": False},
            },
            save=Mock(),
        )
        project = {
            "id": "disposable", "name": "Sniper Test",
            "path": "/tmp/Sniper Test.palmier",
        }
        prior = {"project": None, "surface": {
            "openCount": 0, "openProjects": []}}
        with patch(
                "palmier.live_acceptance_cleanup.restore_project",
                return_value={"openState": prior["surface"]}), patch(
                    "palmier.live_acceptance_cleanup._restore_local"), patch(
                        "palmier.live_acceptance_cleanup.require_surface",
                        return_value=prior["surface"]), patch(
                            "palmier.live_acceptance_cleanup.trash_disposable"
                        ) as trash:
            errors = cleanup_cohort(Mock(), evidence, prior, project)
        self.assertEqual(errors, [])
        trash.assert_not_called()
        self.assertEqual(
            evidence.value["cleanup"]["retainedForReview"], project["path"])


if __name__ == "__main__":
    unittest.main()
