"""Role packets: complete instruction sections, frozen artifacts and safe paths.

Fixtures are TEST-labelled synthetic plans; no packet here grants or implies any review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context as entry
import role_packet_files as files
from role_packet_catalog import CHECKS, INSTRUCTIONS, ROLES
from role_packet_sections import SectionError, heading_span, instruction_row, markdown_headings
import role_packets as packets
from role_packet_text import render_role_packet
from role_packets import RoleRequest, resolve_role_packet
from _role_packet_fixture import RolePacketFixture, sha

REPO = entry.REPO


class SectionTests(RolePacketFixture):
    """Every governing selector resolves; renamed sections fail closed; code fences are not headings."""

    def test_every_role_catalog_resolves_against_current_docs(self) -> None:
        """All four roles resolve every file and section to exact 1-based line ranges."""
        for role in ROLES:
            for spec in INSTRUCTIONS[role]:
                row = instruction_row(REPO, spec)
                self.assertEqual(row["sha256"], sha(Path(row["path"])), row["path"])
                self.assertTrue(all(1 <= s["startLine"] <= s["endLine"] <= row["lines"] for s in row["sections"]))

    def test_check_sources_are_in_repo_documents_or_code(self) -> None:
        """Every required check cites repository files only; no workstation paths or job data."""
        for role, rows in CHECKS.items():
            for identifier, text, source in rows:
                self.assertNotRegex(text + source, r"/Users/|[A-Za-z]:\\|img-\d", identifier)
                for part in source.split("; "):
                    relative = part.split("#")[0].split(" (")[0].strip()
                    self.assertTrue((REPO / relative).exists(), f"{role} {identifier}: {relative}")

    def test_renamed_heading_fails_closed(self) -> None:
        """A selector that no longer matches raises instead of silently dropping the section."""
        self.write("doc.md", "# Title\n## Kept\ntext\n")
        with self.assertRaisesRegex(SectionError, "doc.md: heading '## Renamed' matched 0 times"):
            instruction_row(self.root, ("doc.md", (("heading", "## Renamed"),), "TEST"))

    def test_fenced_code_is_not_a_heading(self) -> None:
        """A shell comment inside a fence cannot truncate the surrounding section."""
        lines = ["## Section", "```bash", "# comment", "```", "after", "## Next"]
        self.assertEqual([row[2] for row in markdown_headings(lines)], ["## Section", "## Next"])
        self.assertEqual(heading_span(lines, "## Section"), (0, 4))

    def test_native_short_route_reads_include_early_preflight(self) -> None:
        """The native-Short context route lists the static preflight document."""
        args = type("Args", (), {"project": None, "workflow": "native-short", "probe_tools": False})()
        with patch.object(entry, "inventory", return_value={}):
            report = entry.build_context(args)
        self.assertIn(str(REPO / "docs/producer/NATIVE_PREFLIGHT.md"), [row["path"] for row in report["requiredReads"]])


class FileTests(RolePacketFixture):
    """Strict observation, linked media, bindings and proposed versions."""

    def test_earlier_records_are_version_ordered_and_explicitly_bounded(self) -> None:
        """v2 sorts before v10; drafts and packets are excluded; more than the bound is an explicit error."""
        from role_packet_native import MAX_PREVIOUS_RECORDS, previous_records
        for name in ("PREBUILD-REVIEW-v10.json", "PREBUILD-REVIEW-v2.json", "PREBUILD-REVIEW.json",
                     "PREBUILD-REVIEW-v3-PACKET.json", "PREBUILD-REVIEW-v3-OBSERVATIONS.json"):
            self.write(f"clip/{name}", "{}")
        rows = previous_records(self.root / "clip", ("PREBUILD-REVIEW",))
        self.assertEqual([Path(row["path"]).name for row in rows],
                         ["PREBUILD-REVIEW.json", "PREBUILD-REVIEW-v2.json", "PREBUILD-REVIEW-v10.json"])
        for index in range(MAX_PREVIOUS_RECORDS):
            self.write(f"many/MOTION-REVIEW-v{index + 1}.json", "{}")
        with self.assertRaisesRegex(files.ArtifactError, f"holds {MAX_PREVIOUS_RECORDS + 1} earlier review records"):
            self.write("many/MOTION-REVIEW.json", "{}")
            previous_records(self.root / "many", ("MOTION-REVIEW",))

    def test_mount_frames_are_clamped_to_the_program(self) -> None:
        """A mount starting before zero or ending past the program stays inside the frame clock."""
        from fractions import Fraction
        from role_packet_media import mount_events
        self.write("project/index.html", '<div data-composition-src="compositions/a.html" data-start="-1" '
                   'data-duration="9"></div><div data-start="1"><div data-composition-src="compositions/b.html" '
                   'data-start="0" data-duration="1"></div></div>')
        events, nested = mount_events(self.root / "project", Fraction(30), 90)
        self.assertEqual(events, [(0, "compositions/a.html mount starts"), (89, "compositions/a.html mount ends")])
        self.assertEqual(nested, ["compositions/b.html"])

    def test_strict_artifact_refuses_hard_links_and_linked_media_records_them(self) -> None:
        """A handoff hard link blocks strict binding but not a hash-verified media observation."""
        video = self.write("export/review.mp4", "TEST mp4")
        os.link(video, self.root / "handoff.mp4")
        with self.assertRaisesRegex(files.ArtifactError, "2 hard links"):
            files.artifact("video", video, "TEST")
        row = files.linked_media("video", video, "TEST")
        self.assertEqual((row["sha256"], row["links"]), (sha(video), 2))

    def test_binding_refuses_changed_bytes(self) -> None:
        """A {path, sha256} binding whose bytes changed is an error, never a silent rebind."""
        file = self.write("x.json", "{}")
        with self.assertRaisesRegex(files.ArtifactError, "no longer matches"):
            files.bound_artifact("x", {"path": str(file), "sha256": "0" * 64}, "TEST")

    def test_versions_skip_every_used_record_packet_and_draft(self) -> None:
        """Unversioned, versioned, packet and draft names all consume versions."""
        for name in ("PREBUILD-REVIEW.json", "PREBUILD-REVIEW-v8.json", "PREBUILD-REVIEW-v9-PACKET.json", "native-plan-v3.json"):
            self.write(f"clip/{name}", "{}")
        paths = files.proposed_paths(self.root / "clip", "PREBUILD-REVIEW")
        self.assertEqual(paths["version"], 10)
        self.assertEqual(paths["record"].name, "PREBUILD-REVIEW-v10.json")
        self.assertEqual(files.next_sibling(self.root / "clip", "native-plan", ".json").name, "native-plan-v4.json")

    def test_new_output_canonicalizes_its_directory_and_refuses_existing_names(self) -> None:
        """A symlinked parent resolves to its real directory; an existing or dangling name is refused."""
        real = self.root / "real"
        real.mkdir()
        (self.root / "alias").symlink_to(real, target_is_directory=True)
        self.assertEqual(files.new_output(self.root / "alias" / "P.json"), real / "P.json")
        (real / "gone.json").symlink_to(self.root / "missing")
        with self.assertRaisesRegex(files.ArtifactError, "already exists"):
            files.new_output(real / "gone.json")


class ResolutionTests(RolePacketFixture):
    """Synthetic plan-critic and owner packets."""

    def test_plan_critic_packet_freezes_bindings_and_writes_a_judgment_free_draft(self) -> None:
        """Bindings, recorded author, scenes and the exact submission command; the draft holds no verdict."""
        plan = self.plan()
        result = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)
        packet, published = result["packet"], result["published"]
        keys = {row["key"] for row in packet["artifacts"]}
        self.assertTrue({"plan", "request-packet", "request:AGENT-BRIEF.md", "bound-prebuild-review"} <= keys)
        self.assertEqual(packet["authorSessionIds"], ["TEST-author"])
        self.assertFalse(packet["subject"]["boundPrebuildReview"]["current"])
        self.assertEqual(published["packet"], str(self.root / "clip/PREBUILD-REVIEW-v2-PACKET.json"))
        self.assertEqual(packet["submission"]["argv"][4:], ["submit-prebuild", published["packet"],
                                                             published["observations"], published["record"]])
        draft = json.loads(Path(published["observations"]).read_text())
        self.assertEqual(draft["rolePacketSha256"], published["sha256"])
        self.assertEqual(draft["rolePacketSha256"], sha(Path(published["packet"])))
        self.assertIsNone(draft["verdict"])
        self.assertTrue(all(value is None for value in draft["coverage"].values()))
        self.assertEqual([row["note"] for row in draft["scenes"]], [None, None])
        self.assertEqual(draft["reviewer"]["plannerSessionId"], "TEST-author")
        self.assertEqual((draft["schemaVersion"], draft["inspection"], draft["approves"]), (2, [], []))
        self.assertEqual(packet["submission"]["inspection"]["targets"], [])
        self.assertIn("Still frames never establish motion", packet["submission"]["inspection"]["rule"])

    def test_stale_plan_binding_refuses_to_resolve(self) -> None:
        """A request packet changed after the plan bound it stops resolution."""
        plan = self.plan()
        (self.root / "requests/abc/SHORT-REQUEST.json").write_text('{"changed": true}')
        with self.assertRaisesRegex(files.ArtifactError, "request-packet"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)

    def test_visual_plan_must_match_its_recorded_byte_hash(self) -> None:
        """The bound VISUAL-PLAN.json is frozen only when its bytes equal visualPlan.byteHash."""
        visual = self.write("clip/producer/VISUAL-PLAN.json", {"schemaVersion": 1, "TEST": "visual plan"})
        plan = self.plan({"visualPlan": {"path": str(visual), "byteHash": "0" * 64}})
        with self.assertRaisesRegex(files.ArtifactError, "visual-plan.*no longer matches"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)
        plan.unlink()
        plan = self.plan({"visualPlan": {"path": str(visual), "byteHash": sha(visual)}})
        packet = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)["packet"]
        self.assertIn(str(visual), [row["path"] for row in packet["artifacts"]])

    def test_large_media_are_declared_not_rehashed(self) -> None:
        """Recordings above the rehash limit keep their declared hash in declaredMedia."""
        plan = self.plan()
        with patch("role_packet_native.REHASH_LIMIT", 4):
            packet = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)["packet"]
        self.assertEqual([row["observation"] for row in packet["declaredMedia"]], ["declared-not-rehashed"])

    def test_owner_packet_orders_preflight_and_refuses_protected_packet_paths(self) -> None:
        """Early preflight follows build and precedes previews; packets never land inside the project."""
        project = self.root / "clip/native-v2"
        self.write("clip/native-v2/SHORT-PROJECT.json", json.loads(self.plan().read_text()))
        self.write("clip/native-v2/index.html", "<html></html>")
        request = RoleRequest(role="clip-owner", native_project=str(project), author_session="TEST-author",
                              packet_out=str(project / "OWNER-PACKET.json"))
        with self.assertRaisesRegex(files.ArtifactError, "outside"):
            resolve_role_packet(request, REPO)
        result = resolve_role_packet(RoleRequest(role="clip-owner", native_project=str(project)), REPO)
        steps = [row["id"] for row in result["packet"]["submission"]["steps"]]
        self.assertLess(steps.index("build"), steps.index("early-preflight"))
        self.assertLess(steps.index("early-preflight"), steps.index("preview-export"))
        self.assertIn(str(REPO / "docs/producer/NATIVE_PREFLIGHT.md"), [row["path"] for row in result["packet"]["instructions"]])

    def test_packets_never_land_inside_a_staged_project_or_attempt(self) -> None:
        """A plan inside a project, a plan beside a manifest and an attempt target are all refused."""
        plan = self.plan()
        project = self.root / "clip/native-v2"
        self.write("clip/native-v2/SHORT-PROJECT.json", json.loads(plan.read_text()))
        with self.assertRaisesRegex(files.ArtifactError, "outside the staged project or attempt"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(project / "SHORT-PROJECT.json")), REPO)
        manifest = self.write("clip/PROJECT-MANIFEST.json", "{}")
        with self.assertRaisesRegex(files.ArtifactError, "outside the staged project or attempt"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)
        manifest.unlink()
        self.write("attempt/export-request.json", "{}")
        with self.assertRaisesRegex(files.ArtifactError, "outside the staged project or attempt"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan),
                                            packet_out=str(self.root / "attempt/P.json")), REPO)
        self.assertFalse(any(path.name.endswith(("-PACKET.json", "-OBSERVATIONS.json")) for path in self.root.rglob("*")))

    def test_retention_counts_only_typed_motion_passes_from_non_authors(self) -> None:
        """Revise rows, author rows, picture-only passes and untyped historical rows never cover a reused unit."""
        units = [{"id": key, "hash": digit * 64} for key, digit in zip("abcde", "12345")]
        passing, motion = {"verdict": "pass", "materialIssues": []}, {"approves": ["picture", "motion"]}
        rows = [{"reviewer": {"sessionId": "TEST-critic"}, "review": passing, "units": {"a": "1" * 64}, "inspection": motion},
                {"reviewer": {"sessionId": "TEST-critic"}, "review": {"verdict": "revise", "materialIssues": [{}]},
                 "units": {"b": "2" * 64}, "inspection": {"approves": []}},
                {"reviewer": {"sessionId": "TEST-author"}, "review": passing, "units": {"c": "3" * 64}, "inspection": motion},
                {"reviewer": {"sessionId": "TEST-critic"}, "review": passing, "units": {"d": "4" * 64},
                 "inspection": {"approves": ["picture"]}},
                {"reviewer": {"sessionId": "TEST-critic"}, "review": passing, "units": {"e": "5" * 64}},
                {"reviewer": {"sessionId": "TEST-canary"}, "review": passing, "units": {"f": "6" * 64},
                 "inspection": {**motion, "fixture": {"scope": "TEST-native-route-canary-fixture"}}}]
        units.append({"id": "f", "hash": "6" * 64})
        prior = self.write("records/MOTION-REVIEW-v1.json", {"schemaVersion": 1, "reviews": rows})
        parts = {"subject": {"reusedUnits": list("abcdef"), "units": units}, "artifacts": [], "authors": []}
        retention = packets.with_retention(parts, str(prior), {"TEST-author"})["subject"]["retention"]
        self.assertEqual((retention["rows"], retention["missingUnits"]), ([0], ["b", "c", "d", "e", "f"]))

    def checked_export(self, preview_from: str) -> Path:
        """A TEST checked export whose recorded preview evidence no longer exists."""
        project = self.root / "clip/native-v2"
        self.write("clip/native-v2/SHORT-PROJECT.json", json.loads(self.plan().read_text()))
        self.write("clip/native-v2/index.html", "<html></html>")
        video = self.write("clip/final-v1/review.mp4", "TEST synthetic mp4 bytes")
        self.write("clip/final-v1/delivery.json", {"status": "native-short-checked-for-review", "output": str(video),
                   "sha256": sha(video), "audioQuality": [{"name": "TEST", "status": "warn", "measured": "TEST"}]})
        self.write("clip/final-v1/export-request.json", {"project": str(project), "previewFrom": preview_from,
                   "previewReviews": str(self.root / "clip/MOTION-REVIEW-v1.json")})
        return self.root / "clip/final-v1"

    def test_final_packet_reports_unavailable_preview_evidence_instead_of_refusing(self) -> None:
        """A checked export whose preview attempt is gone still gets a packet with coverage marked unknown."""
        export = self.checked_export(str(self.root / "clip/preview-v1/motion-previews.json"))
        result = resolve_role_packet(RoleRequest(role="final-critic", export=str(export)), REPO)
        subject = result["packet"]["subject"]
        self.assertEqual((subject["previewCoverage"]["status"], subject["previewReviews"]["status"]),
                         ("unavailable", "unavailable"))
        self.assertIsNone(subject["uncovered"])
        self.assertEqual([row["frame"] for row in subject["events"]], [60, 89])
        self.assertTrue(all(row["coveredByPreview"] is None for row in subject["events"]))
        text = render_role_packet(result["packet"], result["published"])
        self.assertIn("Preview coverage UNKNOWN", text)
        video = subject["export"]["video"]
        self.assertEqual(result["packet"]["submission"]["inspection"]["targets"],
                         [{"path": video["path"], "sha256": video["sha256"], "frames": [0, 90]}])
        self.assertIn(f"Target frames 0–90: {video['path']} (sha256 {video['sha256']})", text)
        draft = json.loads(Path(result["published"]["observations"]).read_text())
        self.assertEqual((draft["schemaVersion"], draft["frameNotes"], draft["inspection"], draft["approves"]), (2, [], [], []))
        self.assertFalse({"playback", "listening"} & set(draft))

    def test_missing_role_input_exits_with_a_bounded_error(self) -> None:
        """context.py --role without its subject returns 2 and says what is missing."""
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(entry.main(["--role", "motion-critic"]), 2)
        self.assertIn("--role motion-critic requires --preview", json.loads(output.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
