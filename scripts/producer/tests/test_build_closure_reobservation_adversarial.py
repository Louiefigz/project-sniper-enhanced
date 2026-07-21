"""Late-race and root-substitution attacks against build reobservation."""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _build_closure_reobservation_fixture import build_closure_fixture
from headless import build_closure_reobservation as reobservation
from headless.build_closure_reobservation import (
    BuildClosureReobservationError,
    reobserve_build_closure,
)


class BuildClosureReobservationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        self.fixture = build_closure_fixture(self.root)

    def test_identical_source_mirror_cannot_replace_retained_root(
        self,
    ) -> None:
        mirror_temp = tempfile.TemporaryDirectory()
        self.addCleanup(mirror_temp.cleanup)
        mirror = os.path.realpath(mirror_temp.name)
        shutil.copytree(self.root, mirror, dirs_exist_ok=True)
        request = dataclasses.replace(
            self.fixture.request, pipeline_root=mirror
        )
        with self.assertRaisesRegex(
            BuildClosureReobservationError, "retained canonical root"
        ):
            reobserve_build_closure(request, lambda view: None)

    def test_late_mutation_of_earlier_source_fails_final_snapshot(
        self,
    ) -> None:
        first, last = self.fixture.sources[0], self.fixture.sources[-1]
        original = reobservation._source_identity
        state = {"armed": False, "attacked": False}

        def attack(path: str) -> tuple[int, ...]:
            if state["armed"] and path == last and not state["attacked"]:
                with open(first, "ab") as handle:
                    handle.write(b"late mutation")
                state["attacked"] = True
            return original(path)

        def arm(_view: object) -> None:
            state["armed"] = True

        with mock.patch.object(
            reobservation, "_source_identity", side_effect=attack
        ), self.assertRaisesRegex(
            BuildClosureReobservationError, "snapshot changed"
        ):
            reobserve_build_closure(self.fixture.request, arm)
        self.assertTrue(state["attacked"])

    def test_unrelated_tool_child_does_not_change_path_binding(self) -> None:
        tool_root = os.path.dirname(self.fixture.tools[0])
        unrelated = os.path.join(tool_root, "unrelated-child")

        def create_unrelated(_view: object) -> None:
            os.mkdir(unrelated, 0o700)

        outcome = reobserve_build_closure(
            self.fixture.request, create_unrelated
        )
        self.assertIsNone(outcome.observation_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
