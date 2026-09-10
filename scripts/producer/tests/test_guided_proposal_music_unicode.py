"""Actual installed Node trim/code-point parity without provider or media execution."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from _guided_proposal_music_fixture import values
from guided_proposal_music import guided_music_policy, validate_requested_music
from guided_proposal_reframe import _coverage, proposal_trim

JS_SPACES = [9, 10, 11, 12, 13, 32, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288, 65279]
NOT_JS_SPACES = [0x85, 0x1c, 0x1d, 0x1e, 0x1f]


def node_text_facts(texts: list[str]) -> list[dict]:
    """One bounded closed-environment local child supplies independent JS semantics."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("installed Node unavailable for actual cross-runtime parity")
    command = [str(Path(node).resolve()), "-e", "let s='';process.stdin.on('data',x=>s+=x);"
        "process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(x=>"
        "({trim:x.trim(),valid:!!x.trim()&&Array.from(x).length<=128})))));" ]
    result = subprocess.run(command, input=json.dumps(texts), text=True, capture_output=True,
                            timeout=3, check=True, env={"PATH": str(Path(node).parent)})
    return json.loads(result.stdout)


class MusicUnicodeTests(unittest.TestCase):
    """Opaque bytes remain intact; JS substantive emptiness is not Unicode normalization."""

    def test_actual_node_trim_and_metadata_identifier_parity(self) -> None:
        """Exercise every JS whitespace plus BOM/NEL/control differences and astral bounds."""
        texts = [chr(value) for value in (*JS_SPACES, *NOT_JS_SPACES)]
        texts += ["".join(chr(value) for value in JS_SPACES), "\ufeff A \u00a0", "😀"*128, "😀"*129]
        expected = node_text_facts(texts)
        for text, facts in zip(texts, expected, strict=True):
            plan, _candidate, _packet, manifest = values()
            manifest["music"][0]["id"] = text
            self.assertEqual(proposal_trim(text), facts["trim"])
            if facts["valid"]:
                self.assertEqual(guided_music_policy(plan, manifest)["assets"][0]["assetId"], text)
                continue
            with self.assertRaises(RuntimeError):
                guided_music_policy(plan, manifest)

    def test_schema_semantics_keep_mixed_and_nonjs_control_ids_exact(self) -> None:
        """The original schema7 parser and metadata gate agree without modifying IDs."""
        for identity in ("\ufeff A \u00a0", "\u0085", "\u001c", "😀"*128):
            plan, candidate, packet, manifest = values()
            manifest["music"][0]["id"] = identity
            candidate["music"]["assetId"] = packet["proposal"]["operations"][0]["music"]["assetId"] = identity
            packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
            before = deepcopy((plan, candidate, packet, manifest))
            self.assertEqual(validate_requested_music(plan, candidate, packet, manifest)["id"], identity)
            self.assertEqual((plan, candidate, packet, manifest), before)

    def test_raw_request_emptiness_uses_exact_js_trim_not_python_strip(self) -> None:
        """Raw request coverage remains exact even for JS-substantive C0/NEL characters."""
        for point in (*JS_SPACES, *NOT_JS_SPACES):
            packet = values()[2]
            text = chr(point)
            packet["rawRequest"]["rawIntent"] = text
            packet["proposal"]["clauses"][0].update(start=0, end=1, quote=text)
            if point in NOT_JS_SPACES:
                _coverage(packet["proposal"], packet)
                continue
            with self.assertRaisesRegex(RuntimeError, "rawRequest"):
                _coverage(packet["proposal"], packet)


if __name__ == "__main__":
    unittest.main()
