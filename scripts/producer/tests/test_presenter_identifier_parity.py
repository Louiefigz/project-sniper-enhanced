"""Actual TS/Python opaque-ID parity; bounded local Node, no providers or media."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from graphics.presenter_layout_contract import PresenterCanvas
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_presenter_assets import select_presenter_assets
from test_guided_presenter_assets import _metadata, _window
from test_presenter_layout_geometry import _payload

_JS_SPACES = (9, 10, 11, 12, 13, 32, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288, 65279)
_OTHER_CONTROLS = (0, 0x85, 0x1c, 0x1d, 0x1e, 0x1f, 0x200b)
_TEXTS = [chr(point) for point in (*_JS_SPACES, *_OTHER_CONTROLS)]
_TEXTS += ["\ufeff A \u00a0", "\nword\r\n", "\ufeff\u0085\ufeff", "😀" * 128, "😀" * 129]


def _node_contract(texts: list[str]) -> list[dict]:
    """Call the actual TS stringValue export once with fixed, bounded TEST inputs."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Actual Node is required for the presenter parity test")
    executable = Path(node).resolve()
    source = "const {stringValue}=require('./src/lib/producer/contracts/validation.ts');let s='';" \
        "process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(" \
        "JSON.stringify(JSON.parse(s).map(x=>{try{return {ok:true,text:stringValue(x,'TEST id',128)}}" \
        "catch{return {ok:false}}}))));"
    result = subprocess.run([str(executable), "--import", "tsx", "-e", source],
        input=json.dumps(texts), text=True, capture_output=True, check=True, timeout=5,
        cwd=Path(__file__).resolve().parents[3],
        env={"PATH": str(executable.parent), "TSX_DISABLE_CACHE": "1"})
    if len(result.stdout.encode()) > 16_384 or result.stderr:
        raise RuntimeError("Presenter parity child produced unexpected output")
    return json.loads(result.stdout)


def _geometry_fact(text: str, field: str) -> dict:
    """Exercise each actual geometry ID field without changing its retained text."""
    payload = _payload()
    payload[field] = [text] if field == "sourceIds" else text
    try:
        value = compile_presenter_geometry(payload, PresenterCanvas(1920, 1080, 120, "yuv420p"), (0, 60))
    except ValueError:
        return {"ok": False}
    identity = value.declaration.source_ids[0] if field == "sourceIds" else value.declaration.asset_id
    return {"ok": True, "text": identity}


def _bridge_fact(text: str, selected: bool) -> dict:
    """Test catalog-only and full selected paths against the same actual TS result."""
    row, entry = _metadata()
    window, manifest = _window(), {"broll": [row]}
    if selected:
        row["id"] = window["layout"]["assetId"] = text
        window["layout"]["sourceIds"] = [text]
    else:
        manifest["broll"].append({"id": text})
    try:
        result = select_presenter_assets({"presenterLayouts": [window]}, manifest, [entry],
                                        PresenterCanvas(1920, 1080, 120, "yuv420p"))
    except ValueError:
        return {"ok": False}
    identity = result[0].admission.asset_id if selected else manifest["broll"][1]["id"]
    return {"ok": True, "text": identity}


class PresenterIdentifierParityTests(unittest.TestCase):
    """No Unicode normalization, lost controls, copied approval or new ID policy."""

    @classmethod
    def setUpClass(cls) -> None:
        """Acquire the actual bounded installed TypeScript result once per cohort."""
        cls.facts = _node_contract(_TEXTS)

    def test_actual_contract_distinguishes_ecmascript_and_python_whitespace(self) -> None:
        """FEFF and line separators are empty; NEL/C0/zero-width controls are opaque."""
        indexed = dict(zip(_TEXTS, self.facts, strict=True))
        self.assertEqual(indexed["\ufeff"], {"ok": False})
        self.assertEqual(indexed["\u2028"], {"ok": False})
        for point in _OTHER_CONTROLS:
            self.assertEqual(indexed[chr(point)], {"ok": True, "text": chr(point)})

    def test_actual_source_and_asset_geometry_identifiers_match_typescript(self) -> None:
        """Both declaration fields preserve accepted code points and reject JS blanks."""
        for text, expected in zip(_TEXTS, self.facts, strict=True):
            with self.subTest(text=repr(text)):
                self.assertEqual(_geometry_fact(text, "sourceIds"), expected)
                self.assertEqual(_geometry_fact(text, "assetId"), expected)

    def test_unselected_broll_id_validation_matches_actual_typescript(self) -> None:
        """Geometry does not mask the independent whole-catalog ID regression."""
        for text, expected in zip(_TEXTS, self.facts, strict=True):
            with self.subTest(text=repr(text)):
                self.assertEqual(_bridge_fact(text, False), expected)

    def test_full_selected_bridge_preserves_exact_accepted_identity(self) -> None:
        """Selected manifest and declared source/asset IDs survive the complete join."""
        for text, expected in zip(_TEXTS, self.facts, strict=True):
            with self.subTest(text=repr(text)):
                self.assertEqual(_bridge_fact(text, True), expected)


if __name__ == "__main__":
    unittest.main()
