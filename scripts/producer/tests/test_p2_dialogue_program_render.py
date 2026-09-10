"""Production-boundary gates for exact dialogue-aware program audio."""
from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _p2_dialogue_program_fixture import (
    FFMPEG,
    DialogueProgramFixture,
    ProgramRequestSpec,
    supports_rubberband,
)
from audio.dialogue_program_contracts import parse_dialogue_program_request
from audio.dialogue_program_render import (
    EXECUTION_NAME,
    GRAPH_NAME,
    PROGRAM_NAME,
    RECEIPT_NAME,
    render_dialogue_program,
)
from audio.dialogue_program_receipt import verify_dialogue_program_receipt
from audio.dialogue_program_media import program_mix_policy
from audio.dialogue_stem_contracts import DialogueStemRenderError
from contracts.schema_validator import validate_document
from current_render_graph_contract import object_hash, validate_graph
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256


def _spec(
    mode: str,
    dialogue: str,
    program: str,
    auxiliary_version: int,
) -> ProgramRequestSpec:
    return ProgramRequestSpec(
        mode, dialogue, program, auxiliary_version)


@unittest.skipUnless(
    supports_rubberband(), "FFmpeg with rubberband is required")
class DialogueProgramRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = self.temp.name
        self.fixture = DialogueProgramFixture(self.root)

    def tearDown(self) -> None:
        for root, directories, files in os.walk(
                self.root, topdown=False):
            for name in files:
                os.chmod(os.path.join(root, name), 0o600)
            for name in directories:
                os.chmod(os.path.join(root, name), 0o700)
        self.temp.cleanup()

    def _request(
        self,
        spec: ProgramRequestSpec,
    ) -> dict:
        return self.fixture.request(spec)

    def _direct(self, request: dict) -> dict:
        return render_dialogue_program(
            parse_dialogue_program_request(request))

    def _cli(self, request: dict, name: str) -> dict:
        request_path = self.fixture.write_request(name, request)
        producer = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(producer), env.get("PYTHONPATH", ""))))
        result = subprocess.run(
            [sys.executable, str(
                producer / "audio" / "dialogue_program_cli.py"),
             request_path],
            text=True, capture_output=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        return payload["receipt"]

    def test_incremental_program_equals_forced_full_and_keeps_auxiliary(
        self,
    ) -> None:
        cold_request = self._request(_spec(
            "incremental", "dialogue-cache", "program-cold", 1))
        cold = self._direct(cold_request)
        incremental_request = self._request(_spec(
            "incremental", "dialogue-cache", "program-incremental", 2))
        incremental = self._cli(
            incremental_request, "incremental-request.json")
        full_request = self._request(_spec(
            "forced-full", "dialogue-full", "program-full", 2))
        full = self._direct(full_request)
        self.assertFalse(cold["reusedDialogueStem"])
        self.assertTrue(incremental["reusedDialogueStem"])
        self.assertFalse(full["reusedDialogueStem"])
        self.assertEqual(
            incremental["dialogue"]["outputSha256"],
            full["dialogue"]["outputSha256"])
        self.assertEqual(
            incremental["output"]["sha256"], full["output"]["sha256"])
        self.assertNotEqual(
            cold["output"]["sha256"], incremental["output"]["sha256"])
        self.assertEqual(
            {row["role"] for row in incremental["auxiliaryProofs"]},
            {"room-tone", "music", "sfx"})
        self._assert_graph_and_seal(incremental_request, incremental)

    def _assert_graph_and_seal(
        self,
        request: dict,
        receipt: dict,
    ) -> None:
        generation = request["programGenerationDir"]
        graph = json.loads(Path(
            generation, GRAPH_NAME).read_text(encoding="utf-8"))
        execution = json.loads(Path(
            generation, EXECUTION_NAME).read_text(encoding="utf-8"))
        program = next(
            row for row in graph["nodes"] if row["nodeId"] == "node-program")
        self.assertEqual(len(program["dependencies"]), 4)
        self.assertIn("node-dialogue", program["dependencies"])
        self.assertEqual(program["inputDigests"]["program.mixPolicy"], object_hash(program_mix_policy()))
        self.assertIn("node-program", execution["dirtyNodeIds"])
        self.assertEqual(receipt["schemaVersion"], 2)
        self.assertEqual((receipt["output"]["codec"], receipt["output"]["sampleFormat"]),
                         ("pcm_f32le", "flt"))
        self.assertEqual(
            execution["reusedNodeIds"],
            ["node-source", "node-timeline", "node-dialogue"])
        self.assertEqual(
            file_sha256(Path(generation, PROGRAM_NAME)),
            receipt["output"]["sha256"])
        self.assertEqual(stat.S_IMODE(os.stat(generation).st_mode), 0o500)
        self.assertEqual(
            set(os.listdir(generation)), {
                "dialogue-track.json", "dialogue-map.json",
                "dialogue-source-set.json", PROGRAM_NAME,
                GRAPH_NAME, EXECUTION_NAME, RECEIPT_NAME,
            })
        for name in os.listdir(generation):
            self.assertEqual(
                stat.S_IMODE(os.stat(Path(generation, name)).st_mode), 0o400)
        broken = copy.deepcopy(graph)
        broken_program = next(
            row for row in broken["nodes"]
            if row["nodeId"] == "node-program")
        broken_program["dependencies"].remove("node-dialogue")
        with self.assertRaisesRegex(RuntimeError, "node-dialogue"):
            validate_graph(broken)

    def test_missing_or_stale_authority_fails_before_any_generation(
        self,
    ) -> None:
        base = self._request(_spec(
            "incremental", "dialogue-never", "program-never", 1))
        cases = []
        bad_count = copy.deepcopy(base)
        bad_count["expectedAuxiliaryCounts"]["sfx"] = 0
        cases.append(bad_count)
        stale_map = copy.deepcopy(base)
        stale_map["authority"]["dialogueMapHash"] = "f" * 64
        cases.append(stale_map)
        unknown = copy.deepcopy(base)
        unknown["legacyPlan"] = True
        cases.append(unknown)
        reordered = copy.deepcopy(base)
        reordered["auxiliaryStems"].reverse()
        cases.append(reordered)
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(DialogueStemRenderError):
                    parse_dialogue_program_request(request)
        self.assertFalse(os.path.lexists(base["dialogueGenerationDir"]))
        self.assertFalse(os.path.lexists(base["programGenerationDir"]))

    def test_misaligned_auxiliary_never_creates_dialogue_or_program(
        self,
    ) -> None:
        request = self._request(_spec(
            "incremental", "dialogue-bad-aux", "program-bad-aux", 1))
        short_path = os.path.join(self.root, "short-music.wav")
        subprocess.run([
            str(FFMPEG), "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i",
            "sine=frequency=221:sample_rate=48000:duration=5.9",
            "-c:a", "pcm_s32le", short_path,
        ], check=True)
        request["auxiliaryStems"][0]["path"] = short_path
        request["auxiliaryStems"][0]["sha256"] = file_sha256(short_path)
        validated = parse_dialogue_program_request(request)
        with self.assertRaisesRegex(
                DialogueStemRenderError, "not exact program PCM"):
            render_dialogue_program(validated)
        self.assertFalse(os.path.lexists(request["dialogueGenerationDir"]))
        self.assertFalse(os.path.lexists(request["programGenerationDir"]))

    def test_receipt_schema_and_self_hash_reject_tampering(self) -> None:
        request = self._request(_spec(
            "forced-full", "dialogue-receipt", "program-receipt", 1))
        receipt = self._direct(request)
        self.assertEqual(validate_document(
            "dialogue-program-receipt-v2.schema.json", receipt), receipt)
        tampered = copy.deepcopy(receipt)
        tampered["expectedAuxiliaryCounts"]["music"] = 0
        with self.assertRaisesRegex(DialogueStemRenderError, "hash drifted"):
            verify_dialogue_program_receipt(tampered)
        body = {key: value for key, value in tampered.items()
                if key != "receiptHash"}
        tampered["receiptHash"] = content_hash(body)
        with self.assertRaisesRegex(
                DialogueStemRenderError, "role closure"):
            verify_dialogue_program_receipt(tampered)
        stale_set = copy.deepcopy(receipt)
        stale_set["auxiliaryProofs"][0]["sha256"] = "f" * 64
        body = {key: value for key, value in stale_set.items()
                if key != "receiptHash"}
        stale_set["receiptHash"] = content_hash(body)
        with self.assertRaisesRegex(
                DialogueStemRenderError, "snapshot hash"):
            verify_dialogue_program_receipt(stale_set)

    def test_legacy_receipt_is_historical_only_and_cannot_describe_float_program(self) -> None:
        request = self._request(_spec("forced-full", "dialogue-v2", "program-v2", 1))
        current = self._direct(request)
        legacy = copy.deepcopy(current)
        legacy["schemaVersion"] = 1
        legacy["output"].update(codec="pcm_s32le", sampleFormat="s32")
        legacy["output"].pop("channelLayoutEvidence")
        legacy["policies"].pop("mixPolicyVersion")
        legacy["policies"].pop("masteringApplied")
        legacy["receiptHash"] = content_hash({k: v for k, v in legacy.items() if k != "receiptHash"})
        self.assertEqual(validate_document("dialogue-program-receipt-v1.schema.json", legacy), legacy)
        with self.assertRaisesRegex(DialogueStemRenderError, "closed schema"):
            verify_dialogue_program_receipt(legacy)
        mislabeled = copy.deepcopy(current)
        mislabeled["output"].update(codec="pcm_s32le", sampleFormat="s32")
        mislabeled["receiptHash"] = content_hash({k: v for k, v in mislabeled.items() if k != "receiptHash"})
        with self.assertRaisesRegex(DialogueStemRenderError, "closed schema"):
            verify_dialogue_program_receipt(mislabeled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
