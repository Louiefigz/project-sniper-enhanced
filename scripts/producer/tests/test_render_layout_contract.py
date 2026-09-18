"""TEST-only metadata faults; no Docker/browser/media or visual qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import time
import unittest
from pathlib import Path

from headless.render_layout_contract import (
    CLI_SHA256, OBSERVER_FILES, POLICY, PIPELINE_POLICY, SCOPE, canonical, role_inventory, validate_request,
)
from headless.render_layout_result import validate_observation
from headless.render_layout_worker import parse_worker_request

ROOT = Path("/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER")


def request() -> dict:
    """A deliberately tiny valid native clock, not a fabricated render receipt."""
    return {"schemaVersion": 1, "profile": POLICY, "snapshotSha256": "a" * 64,
            "composition": "compositions/agenda-slide.html", "frameRate": "30000/1001",
            "totalFrames": 2, "width": 1920, "height": 1080}


def documents(spec: dict | None = None) -> dict[str, bytes]:
    """Actual current template text plus explicit TEST variables, no sealing."""
    return {"motion/compositions/agenda-slide.html":
            (ROOT / "templates/motion/compositions/agenda-slide.html").read_bytes(),
            "request/variables.json": canonical(spec or {"layout": "caption-safe-upper-v1"})}


def fixture() -> tuple[dict, dict, dict]:
    """Synthetic returned metadata has explicit TEST SHA placeholders."""
    held = request()
    inventory = role_inventory(documents())
    sources = [{"path": f"/opt/sniper-motion/container/{name}", "sha256": "b" * 64,
                "sizeBytes": 123} for name in OBSERVER_FILES]
    expected = {"media": {"sha256": "c" * 64, "sizeBytes": 100},
                "observerSources": sources, "roleInventory": inventory}
    roles = [{**row, "bounds": [20, 30, 200, 80], "opacity": 1, "issues": []} for row in inventory]
    frames = [{"frameIndex": i, "timeNumerator": str(i * 1001), "timeDenominator": "30000",
               "captureSha256": "d" * 64, "roles": copy.deepcopy(roles), "issues": []} for i in range(2)]
    value = {"schemaVersion": 1, "kind": "sealed-animation-layout-observation",
             "policy": POLICY, "scope": SCOPE, "request": held,
             "requestSha256": hashlib.sha256(canonical(held)).hexdigest(),
             "cliSha256": CLI_SHA256, "observerSources": sources, "media": expected["media"],
             "frames": frames, "roleInventory": inventory, "framesObserved": 2, "status": "observed"}
    return held, copy.deepcopy(expected), value


class LayoutRequestTests(unittest.TestCase):
    """Fail cheap on unsupported geometry/clock/profile before expensive work."""

    def test_explicit_native_ntsc_request(self) -> None:
        self.assertEqual(validate_request(request()), request())

    def test_no_legacy_or_portrait_coercion(self) -> None:
        for change in ({"profile": "old"}, {"schemaVersion": True}, {"width": 1080, "height": 1920},
                       {"composition": "compositions/pipeline-flow.html"}, {"extra": False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_request({**request(), **change})

    def test_frame_time_and_workload_limits(self) -> None:
        for change in ({"frameRate": "60000/2002"}, {"frameRate": "29.97"},
                       {"frameRate": "30000/1001", "totalFrames": 1800},
                       {"frameRate": "61/1"}, {"totalFrames": True}, {"totalFrames": 3601}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_request({**request(), **change})

    def test_sparse_nonadjacent_slots_keep_exact_role_ids(self) -> None:
        spec = {"layout": "caption-safe-upper-v1", "eyebrow": "", "title1": "",
                "title2": "", "title3": "", "title4": "", "title5": "TEST last", "sub5": ""}
        rows = role_inventory(documents(spec))
        self.assertEqual([row["id"] for row in rows],
                         ["step-5-marker", "step-5-title", "title", "title-accent"])
        self.assertEqual(rows[1]["text"], "TEST last")

    def test_four_present_steps_are_not_silently_dropped(self) -> None:
        with self.assertRaises(ValueError):
            role_inventory(documents({"layout": "caption-safe-upper-v1", "title4": "also"}))


class LayoutResultTests(unittest.TestCase):
    """Structural all-frame proof never upgrades missing/unsupported paint."""

    def test_whole_frame_metadata_accepts_exact_held_identities(self) -> None:
        held, expected, value = fixture()
        self.assertIs(validate_observation(value, held, expected), value)

    def test_four_actual_sparse_roles_are_supported(self) -> None:
        held, expected, value = fixture()
        keep = {"step-1-marker", "step-1-title", "title", "title-accent"}
        value["roleInventory"] = [row for row in value["roleInventory"] if row["id"] in keep]
        expected["roleInventory"] = copy.deepcopy(value["roleInventory"])
        for frame in value["frames"]:
            frame["roles"] = [row for row in frame["roles"] if row["id"] in keep]
        validate_observation(value, held, expected)

    def test_unknown_or_missing_role_even_repeated_every_frame_rejects(self) -> None:
        held, expected, value = fixture()
        value["roleInventory"][0]["id"] = ""
        for frame in value["frames"]:
            frame["roles"][0]["id"] = ""
        with self.assertRaises(ValueError):
            validate_observation(value, held, expected)

    def test_missing_duplicate_reordered_or_wrong_seek_frame_rejects(self) -> None:
        for mutate in (lambda v: v["frames"].pop(), lambda v: v["frames"].reverse(),
                       lambda v: v["frames"][1].update(frameIndex=0),
                       lambda v: v["frames"][1].update(timeNumerator="1000")):
            held, expected, value = fixture()
            mutate(value)
            with self.assertRaises(ValueError):
                validate_observation(value, held, expected)

    def test_shadow_cannot_claim_observed(self) -> None:
        held, expected, value = fixture()
        value["frames"][0]["roles"][0]["issues"] = ["unsupported-textShadow"]
        with self.assertRaises(ValueError):
            validate_observation(value, held, expected)
        value["status"] = "unqualified"
        validate_observation(value, held, expected)

    def test_outside_canvas_cannot_be_reported_supported(self) -> None:
        held, expected, value = fixture()
        value["frames"][0]["roles"][0]["bounds"] = [20, 1000, 200, 1100]
        with self.assertRaises(ValueError):
            validate_observation(value, held, expected)

    def test_missing_visible_bounds_and_nonfinite_measurements_reject(self) -> None:
        for change in ({"bounds": None}, {"bounds": [0, 0, float("nan"), 40]},
                       {"opacity": True}, {"bounds": [0, 0, 0, 40]}):
            held, expected, value = fixture()
            value["frames"][0]["roles"][0].update(change)
            with self.assertRaises(ValueError):
                validate_observation(value, held, expected)

    def test_never_visible_required_role_remains_unqualified(self) -> None:
        held, expected, value = fixture()
        for frame in value["frames"]:
            frame["roles"][0].update(bounds=None, opacity=0)
        with self.assertRaises(ValueError):
            validate_observation(value, held, expected)
        value["status"] = "unqualified"
        validate_observation(value, held, expected)

    def test_actual_text_media_request_and_implementation_binding(self) -> None:
        for mutate in (lambda v: v.update(cliSha256="f" * 64),
                       lambda v: v.update(requestSha256="f" * 64),
                       lambda v: v["media"].update(sha256="f" * 64),
                       lambda v: v["frames"][1]["roles"][0].update(text="hidden change")):
            held, expected, value = fixture()
            expected = copy.deepcopy(expected)
            mutate(value)
            with self.assertRaises(ValueError):
                validate_observation(value, held, expected)


def pipeline_documents(patch: dict | None = None) -> dict[str, bytes]:
    """Actual pipeline source and explicit TEST-only non-preview copy."""
    spec = {"layout": "caption-safe-upper-v1", "nodes": "01~One|02~Two", **(patch or {})}
    return {"motion/compositions/module-pipeline.html":
            (ROOT / "templates/motion/compositions/module-pipeline.html").read_bytes(),
            "request/variables.json": canonical(spec)}


def pipeline_fixture() -> tuple[dict, dict, dict]:
    """Closed synthetic metadata for the new profile, not actual native proof."""
    held, expected, value = fixture()
    held.update(profile=PIPELINE_POLICY, composition="compositions/module-pipeline.html")
    inventory = role_inventory(pipeline_documents(), PIPELINE_POLICY)
    expected["roleInventory"] = copy.deepcopy(inventory)
    value.update(policy=PIPELINE_POLICY, request=copy.deepcopy(held), roleInventory=inventory,
                 requestSha256=hashlib.sha256(canonical(held)).hexdigest())
    for frame in value["frames"]:
        frame["roles"] = [{**row, "bounds": [20, 30, 200, 80], "opacity": 1, "issues": []} for row in inventory]
    return held, expected, value


class PipelineLayoutTests(unittest.TestCase):
    """Separate pipeline policy never enlarges the historical agenda class."""

    def test_exact_minimum_roles_include_the_nonlexical_connector(self) -> None:
        """A real connector may not disappear merely because it has no text."""
        held, expected, value = pipeline_fixture()
        self.assertEqual(expected["roleInventory"], [{"id": "connector-1", "text": ""},
            {"id": "node-1", "text": "01One"}, {"id": "node-2", "text": "02Two"}])
        self.assertIs(validate_observation(value, held, expected), value)

    def test_full_six_node_inventory_preserves_all_sixteen_roles(self) -> None:
        """No label, connector, headline or footnote may be dropped to fit."""
        spec = {"nodes": "|".join(f"{index}~Node {index}" for index in range(1, 7)),
                "eyebrow": " TEST ", "headlineLines": " First | Second ",
                "explainer": " Full copy ", "footChip": " Source "}
        before = copy.deepcopy(spec)
        roles = role_inventory(pipeline_documents(spec), PIPELINE_POLICY)
        self.assertEqual(len(roles), 16)
        self.assertEqual([row["id"] for row in roles[:5]], [f"connector-{index}" for index in range(1, 6)])
        self.assertEqual(spec, before)

    def test_no_preview_bad_content_or_unqualified_paint_fallback(self) -> None:
        """Malformed native intent fails rather than substituting preview copy."""
        for patch in ({"nodes": ""}, {"nodes": "1~one"}, {"nodes": "1~one|2~"},
                      {"nodes": "|".join(f"{i}~node" for i in range(7))},
                      {"headlineLines": "a||b"}, {"headlineLines": "a|"},
                      {"eyebrow": True}, {"exit": "blur-recede"},
                      {"presenterFrame": True}, {"presenterFrame": 0}, {"layout": "full-canvas"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                role_inventory(pipeline_documents(patch), PIPELINE_POLICY)

    def test_cross_profile_or_missing_connector_even_in_every_frame_rejects(self) -> None:
        """Caller-held independent inventory remains mandatory on the new class."""
        held, expected, value = pipeline_fixture()
        with self.assertRaises(ValueError):
            validate_request({**held, "profile": POLICY})
        with self.assertRaises(ValueError):
            validate_request({**held, "composition": request()["composition"]})
        with self.assertRaises(ValueError):
            validate_observation({**value, "policy": POLICY}, held, expected)
        value["roleInventory"] = value["roleInventory"][1:]
        for frame in value["frames"]:
            frame["roles"] = frame["roles"][1:]
        with self.assertRaises(ValueError):
            validate_observation(value, held, expected)

    def test_worker_operation_is_bound_to_exact_native_profile(self) -> None:
        """Cheap invocation checks precede any archive read or media launch."""
        observation, _, _ = pipeline_fixture()
        value = {"schemaVersion": 2, "operation": "observe-sealed-pipeline-layout",
                 "snapshot": {"path": "/private/tmp/TEST-layout-input.tar", "sha256": "a" * 64, "manifest": []},
                 "observation": observation, "outputPath": "/private/tmp/TEST-layout-output.mp4",
                 "containerName": "TEST-unused", "expiresAtUnixMs": time.time() * 1000 + 10000}
        self.assertEqual(parse_worker_request(value).observation, observation)
        with self.assertRaises(ValueError):
            parse_worker_request({**value, "operation": "observe-sealed-agenda-layout"})


if __name__ == "__main__":
    unittest.main()
