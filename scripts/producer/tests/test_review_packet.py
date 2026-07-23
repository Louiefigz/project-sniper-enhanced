"""review_packet tests — determinism + content completeness of the critic packet.

The skill review wall (SKILL.md step 4) hands one hash-bound evidence packet to
its round-1 critics. These tests pin the two contract properties the doctrine
leans on: same inputs → same ``contentDigest`` (in-process AND across the CLI),
and the packet carries every evidence block the critics read (plan/manifest
byte hashes, cut table + rationales, kept-word remap, boundary neighbors, gate
verdicts, pacing report).
"""
import hashlib
import unittest

from _common import *  # noqa: F401,F403
import review_packet as rp


def _word(text: str, start: float, dur: float = 0.3) -> dict:
    return {"word": text, "punctuated_word": text,
            "start": round(start, 3), "end": round(start + dur, 3)}


def _utt(start: float, text: str) -> dict:
    words, t = [], start
    for token in text.split():
        words.append(_word(token, t))
        t += 0.5
    return {"start": words[0]["start"], "end": words[-1]["end"],
            "text": text, "words": words}


TRANSCRIPT = {"transcript": [
    _utt(0.4, "We made zero sales this month"),
    _utt(5.0, "Here is the fix that works"),
    _utt(14.8, "this stretch gets cut entirely"),
    _utt(21.0, "Ship the system today"),
]}
_WORD_TOTAL = sum(len(u["words"]) for u in TRANSCRIPT["transcript"])


def _fixture_plan() -> dict:
    plan = good_plan()
    plan["cutTrack"] = [
        {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0,
         "rationale": "hook: the zero-sales problem"},
        {"sourceId": "raw-1", "start": 20.0, "end": 30.0, "speed": 2.0,
         "rationale": "payoff: ship the system"},
    ]
    return plan


class ReviewPacketTests(unittest.TestCase):
    """Build once against a real on-disk fixture; every test reads the packet."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="review-packet-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        manifest = copy.deepcopy(MANIFEST)
        manifest["sources"][0]["transcriptPath"] = "raw-1.transcript.json"
        cls.plan_path = os.path.join(cls.tmp, "edit_plan.json")
        cls.manifest_path = os.path.join(cls.tmp, "asset_manifest.json")
        cls.transcript_path = os.path.join(cls.tmp, "raw-1.transcript.json")
        for path, payload in ((cls.plan_path, _fixture_plan()),
                              (cls.manifest_path, manifest),
                              (cls.transcript_path, TRANSCRIPT)):
            with open(path, "w") as fh:
                json.dump(payload, fh, indent=2)
        cls.packet = rp.build_packet(cls.plan_path, cls.tmp, cls.manifest_path)

    # ------------------------------------------------------------------ #
    # Determinism
    # ------------------------------------------------------------------ #
    def test_same_inputs_same_packet(self) -> None:
        rebuilt = rp.build_packet(self.plan_path, self.tmp, self.manifest_path)
        self.assertEqual(rebuilt["contentDigest"], self.packet["contentDigest"])
        self.assertEqual(json.dumps(rebuilt, sort_keys=True),
                         json.dumps(self.packet, sort_keys=True))

    def test_cli_reproduces_the_library_digest(self) -> None:
        out = os.path.join(self.tmp, "packet-cli.json")
        proc = subprocess.run(
            [sys.executable, rp.__file__, self.plan_path, self.tmp,
             self.manifest_path, "--out", out],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = json.loads(proc.stdout)
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["contentDigest"], self.packet["contentDigest"])
        with open(out) as fh:
            written = json.load(fh)
        self.assertEqual(written["contentDigest"], self.packet["contentDigest"])
        self.assertEqual(status["keptWords"],
                         len(self.packet["transcriptEvidence"]["keptWords"]))

    def test_digest_binds_the_content(self) -> None:
        self.assertEqual(rp.packet_content_digest(self.packet),
                         self.packet["contentDigest"])
        tampered = copy.deepcopy(self.packet)
        tampered["timeline"]["segments"][0]["rationale"] = "edited after review"
        self.assertNotEqual(rp.packet_content_digest(tampered),
                            self.packet["contentDigest"])

    def test_plan_edit_changes_the_digest(self) -> None:
        plan = _fixture_plan()
        plan["cutTrack"][1]["rationale"] = "payoff: revised rationale"
        other = os.path.join(self.tmp, "edit_plan_v2.json")
        with open(other, "w") as fh:
            json.dump(plan, fh, indent=2)
        rebuilt = rp.build_packet(other, self.tmp, self.manifest_path)
        self.assertNotEqual(rebuilt["contentDigest"], self.packet["contentDigest"])
        self.assertNotEqual(rebuilt["plan"]["byteHash"],
                            self.packet["plan"]["byteHash"])

    # ------------------------------------------------------------------ #
    # Content completeness
    # ------------------------------------------------------------------ #
    def _file_sha(self, path: str) -> str:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def test_byte_hashes_bind_the_exact_files(self) -> None:
        self.assertEqual(self.packet["plan"]["byteHash"],
                         self._file_sha(self.plan_path))
        self.assertEqual(self.packet["manifest"]["byteHash"],
                         self._file_sha(self.manifest_path))
        self.assertEqual(self.packet["transcriptEvidence"]["transcripts"][0]["byteHash"],
                         self._file_sha(self.transcript_path))

    def test_segment_table_carries_geometry_and_rationale(self) -> None:
        segments = self.packet["timeline"]["segments"]
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["rationale"], "hook: the zero-sales problem")
        self.assertEqual(segments[1]["sourceId"], "raw-1")
        self.assertEqual(segments[1]["speed"], 2.0)
        self.assertEqual(segments[1]["outputStart"], 10.0)
        self.assertEqual(segments[1]["outputEnd"], 15.0)
        self.assertEqual(self.packet["timeline"]["outputDuration"], 15.0)

    def test_kept_words_remap_through_the_cut(self) -> None:
        kept = self.packet["transcriptEvidence"]["keptWords"]
        by_word = {w["word"]: w for w in kept}
        ship = by_word["Ship"]  # source 21.0 → 10 + (21-20)/2
        self.assertEqual(ship["outputStart"], 10.5)
        self.assertEqual(ship["outputEnd"], 10.65)
        self.assertEqual(ship["segmentIndex"], 1)
        self.assertEqual(ship["sourceId"], "raw-1")
        self.assertNotIn("stretch", by_word)   # 15.3s sits in the 10-20 cut
        self.assertNotIn("entirely", by_word)
        starts = [w["outputStart"] for w in kept]
        self.assertEqual(starts, sorted(starts))

    def test_boundary_neighbors_quote_the_edge_words(self) -> None:
        rows = {(r["segmentIndex"], r["edge"]): r
                for r in self.packet["transcriptEvidence"]["boundaryNeighbors"]}
        self.assertEqual(len(rows), 4)          # 2 segments × in/out
        seg1_in = rows[(1, "in")]
        self.assertEqual(seg1_in["sourceTime"], 20.0)
        self.assertEqual(seg1_in["before"]["word"], "entirely")
        self.assertEqual(seg1_in["after"]["word"], "Ship")
        self.assertIsNone(rows[(0, "in")]["before"])
        self.assertEqual(rows[(0, "in")]["after"]["word"], "We")

    def test_gate_verdicts_and_digest(self) -> None:
        gates = self.packet["gates"]
        self.assertEqual(sorted(gates), ["claimsContract", "hookContract", "planLint"])
        for verdict in gates.values():
            self.assertIn("ok", verdict)
            self.assertIsInstance(verdict["errors"], list)
            self.assertIsInstance(verdict["warnings"], list)
        self.assertIn("scope", gates["hookContract"])
        self.assertEqual(self.packet["gateDigest"], rp._digest(gates))

    def test_pacing_report_matches_the_cli_shape(self) -> None:
        pacing = self.packet["pacing"]
        for key in ("mode", "outputDurationS", "changesPerMin", "longestGapS",
                    "gaps", "hookRatio", "suggestedFills"):
            self.assertIn(key, pacing)
        self.assertEqual(pacing["mode"], "short")
        self.assertEqual(pacing["outputDurationS"], 15.0)

    def test_transcript_evidence_counts(self) -> None:
        evidence = self.packet["transcriptEvidence"]
        row = evidence["transcripts"][0]
        self.assertEqual(row["sourceId"], "raw-1")
        self.assertEqual(row["utteranceCount"], 4)
        self.assertEqual(row["sourceWordCount"], _WORD_TOTAL)
        self.assertEqual(len(row["utterances"]), 4)
        self.assertEqual(evidence["missingTranscriptSourceIds"], ["raw-2"])

    # ------------------------------------------------------------------ #
    # Fail-closed
    # ------------------------------------------------------------------ #
    def test_kept_source_without_transcript_fails_closed(self) -> None:
        manifest = copy.deepcopy(MANIFEST)   # raw-1 has no transcriptPath here
        path = os.path.join(self.tmp, "manifest-no-transcript.json")
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        with self.assertRaisesRegex(ValueError, "no transcript"):
            rp.build_packet(self.plan_path, self.tmp, path)

    def test_unknown_cut_source_fails_closed(self) -> None:
        plan = _fixture_plan()
        plan["cutTrack"][0]["sourceId"] = "ghost"
        path = os.path.join(self.tmp, "plan-ghost.json")
        with open(path, "w") as fh:
            json.dump(plan, fh)
        with self.assertRaisesRegex(ValueError, "unknown source ghost"):
            rp.build_packet(path, self.tmp, self.manifest_path)


if __name__ == "__main__":
    unittest.main()
