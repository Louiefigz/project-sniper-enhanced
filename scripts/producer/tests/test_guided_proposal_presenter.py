"""Pure V8 intake/policy regressions; no provider, media or real approval."""
from __future__ import annotations

from copy import deepcopy
from itertools import product
import unittest

from _guided_proposal_presenter_fixture import asset, noop, operation, values
from guided_proposal_presenter import guided_presenter_policy, validate_requested_presenter
from guided_proposal_music import guided_music_policy, validate_requested_music


class PresenterRequestTests(unittest.TestCase):
    """Actual request, accepted cut and metadata remain separate immutable inputs."""

    def test_all_three_layouts_rederive_without_mutating_or_granting_authority(self) -> None:
        """Returned geometry is the actual operation, not a relabeled V7 request."""
        for kind in ("inset", "bubble", "split"):
            rows = values(kind)
            before = deepcopy(rows)
            result = validate_requested_presenter(*rows)
            self.assertEqual(list(result.windows), rows[1]["presenterLayouts"])
            self.assertEqual(rows, before)
            self.assertEqual(result.prior_packet["proposal"]["schemaVersion"], 7)
            self.assertEqual(result.prior_packet["evidence"]["schemaVersion"], 7)
            self.assertEqual(result.prior_packet["proposal"]["operations"][0]["type"], "preserve-cut")
            self.assertNotIn("presenterLayout", result.prior_packet["proposal"]["operations"][0])
            result.windows[0]["layout"]["assetId"] = "changed"
            self.assertEqual(rows, before)

    def test_actual_prior_music_index_survives_validation_only_view(self) -> None:
        """The real packet retains V8 layout and music indices; only the old lane gets a view."""
        music = noop()
        music.update(type="music-bed-full-program", reason="Use the explicitly requested TEST music bed.",
            music={"schemaVersion": 1, "assetId": "bed", "gapDb": 11, "duck": True})
        plan, candidate, packet, manifest = values(operations=[music, operation()])
        plan["target"]["music"] = candidate["target"]["music"] = packet["evidence"]["target"]["music"] = True
        manifest["music"] = [{**asset(), "id": "bed", "duration": 3}]
        packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
        candidate["music"] = {"enabled": True, "assetId": "bed", "gapDb": 11, "duck": True}
        before = deepcopy(packet)
        selected = validate_requested_presenter(plan, candidate, packet, manifest)
        self.assertEqual(selected.windows[0]["operationIndex"], 1)
        self.assertEqual(validate_requested_music(plan, candidate, selected.prior_packet, manifest), manifest["music"][0])
        self.assertEqual(packet, before)

    def test_exact_target_pair_or_unchanged_target_only(self) -> None:
        """Full builder decoration is allowed; arbitrary/one-sided changes remain rejected."""
        plan, candidate, packet, manifest = values()
        pair = {key: packet["proposal"][key] for key in ("graphicsStyle", "graphicsStyleRationale")}
        candidate["target"].update(pair)
        validate_requested_presenter(plan, candidate, packet, manifest)
        changes = [{"width": 1080}, {"scope": "full"}, {"lanes": {"motion": "off"}}, {"extra": None},
                   {"graphicsStyle": "bad"}, {"graphicsStyleRationale": "changed reason"}]
        for change in changes:
            altered = deepcopy(candidate)
            altered["target"].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, "target"):
                validate_requested_presenter(plan, altered, packet, manifest)
        for missing in pair:
            altered = deepcopy(candidate)
            del altered["target"][missing]
            with self.assertRaisesRegex(RuntimeError, "target"):
                validate_requested_presenter(plan, altered, packet, manifest)

    def test_historical_versions_only_preserve_inherited_layouts(self) -> None:
        """Old versions never gain presenter authorization or a fabricated V7 view."""
        for version, inherited in product(range(2, 8), (None, [], {"old": True})):
            plan, candidate, packet, manifest = values(operations=[noop()])
            packet["proposal"] = {"schemaVersion": version}
            plan["presenterLayouts"] = candidate["presenterLayouts"] = inherited
            self.assertIsNone(validate_requested_presenter(plan, candidate, packet, manifest))
            del candidate["presenterLayouts"]
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                validate_requested_presenter(plan, candidate, packet, manifest)
        for version in (True, 8.0, "8", 1, 9, None):
            rows = values()
            rows[2]["proposal"]["schemaVersion"] = version
            with self.assertRaisesRegex(RuntimeError, "integer proposal"):
                validate_requested_presenter(*rows)

    def test_v8_noop_requires_exact_policy_and_keeps_inherited_roots(self) -> None:
        """No-op does not acquire fresh layout or demand new frame/media authority."""
        plan, candidate, packet, manifest = values(operations=[noop()])
        for key in ("presenterLayouts", "presenter", "overlays"):
            plan[key] = candidate[key] = None
        del packet["evidence"]["frameRate"]
        self.assertEqual(validate_requested_presenter(plan, candidate, packet, manifest).windows, ())
        packet["evidence"]["presenterPolicy"]["acceptedMotionEnabled"] = False
        with self.assertRaisesRegex(RuntimeError, "policy"):
            validate_requested_presenter(plan, candidate, packet, manifest)

    def test_cuts_legacy_roots_and_rehashed_windows_remain_exact(self) -> None:
        """Hashing an altered candidate cannot make it the actual requested projection."""
        for key, change in (("cutTrack", []), ("cutDecisions", {}), ("presenter", None), ("overlays", []), ("presenterLayouts", [])):
            rows = values()
            rows[1][key] = change
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_requested_presenter(*rows)
        for change in ({"operationIndex": 1}, {"startFrame": 41}, {"endFrameExclusive": 561}):
            rows = values()
            rows[1]["presenterLayouts"][0].update(change)
            with self.assertRaisesRegex(RuntimeError, "actual V8"):
                validate_requested_presenter(*rows)

    def test_new_layout_rejects_every_inherited_collision_even_null(self) -> None:
        """Inherited empty/null roots are authority, not permission to replace them."""
        for key, inherited in product(("presenterLayouts", "presenter", "overlays"), (None, [], {})):
            rows = values()
            rows[0][key] = inherited
            if key != "presenterLayouts":
                rows[1][key] = deepcopy(inherited)
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                validate_requested_presenter(*rows)

    def test_scope_and_lanes_cannot_be_invented_or_coerced(self) -> None:
        """Explicit auto does not activate b-roll outside its real accepted scope."""
        targets = [{"scope": "trim", "lanes": {"motion": "auto", "broll": "auto"}}, {"scope": "light"},
            {"lanes": {"motion": "off"}}, {"lanes": {"broll": "operator"}}, {"lanes": {"broll": ["id"]}},
            {"lanes": {"typo": "off"}}, {"lanes": []}, {"lanes": {"motion": True}}, {"scope": None}]
        for target in targets:
            rows = values()
            for value in (rows[0]["target"], rows[1]["target"], rows[2]["evidence"]["target"]):
                value.update(target)
            with self.subTest(target=target), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)

    def test_policy_is_complete_closed_and_no_rights_claim(self) -> None:
        """Extra policy fields, changed order, even invalid unused assets reject."""
        for change in ({"creativeApproved": True}, {"acceptedMotionEnabled": 1}, {"assets": []}, {"schemaVersion": True}):
            rows = values()
            rows[2]["evidence"]["presenterPolicy"].update(change)
            with self.assertRaisesRegex(RuntimeError, "policy"):
                validate_requested_presenter(*rows)
        plan, _, _, manifest = values()
        manifest["broll"][0]["licensed"] = True
        self.assertEqual(guided_presenter_policy(plan, manifest)["assets"][0]["rights"], "unverified")
        manifest["broll"].append({"id": "unused"})
        with self.assertRaises(RuntimeError):
            guided_presenter_policy(plan, manifest)

    def test_all_catalog_metadata_is_bounded_and_strict(self) -> None:
        """No missing refs, duplicate IDs, unsafe size or coerced kind/duration."""
        changes = [{"id": " "}, {"id": "x" * 129}, {"path": " "}, {"originalPath": "x" * 4097},
            {"sourceSha256": "A" * 64}, {"sourceSizeBytes": True}, {"sourceSizeBytes": 2**53},
            {"admissionReceiptSha256": None}, {"kind": "audio"}, {"duration": 1}, {"resolution": [0, 1]},
            {"resolution": [True, 1080]}, {"resolution": [1920]}, {"resolution": [16385, 1]}]
        for change in changes:
            rows = values()
            rows[3]["broll"][0].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        for catalog in (None, {}, [asset()] * 2, [asset()] * 129):
            rows = values()
            rows[3]["broll"] = catalog
            with self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)

    def test_image_zero_and_video_offset_never_imply_video_eligibility(self) -> None:
        """Video rational timing can be authored; actual frame alignment remains an owner check."""
        rows = values()
        for layout in (rows[1]["presenterLayouts"][0]["layout"], rows[2]["proposal"]["operations"][0]["presenterLayout"]):
            layout["assetStart"] = {"numerator": 1, "denominator": 3}
        with self.assertRaisesRegex(RuntimeError, "still image"):
            validate_requested_presenter(*rows)
        rows[3]["broll"][0].update(kind="video", duration=1)
        rows[2]["evidence"]["presenterPolicy"] = guided_presenter_policy(rows[0], rows[3])
        self.assertEqual(validate_requested_presenter(*rows).windows[0]["layout"]["assetStart"], {"numerator": 1, "denominator": 3})


if __name__ == "__main__":
    unittest.main()
