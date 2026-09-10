"""Pure closed metadata/graph parity for the distinct1080p optimization experiment."""
from __future__ import annotations

import re
from pathlib import Path

from graphics import presenter_layout_geometry
from graphics.presenter_layout_contract import PresenterCanvas
from graphics.presenter_layout_geometry import compile_presenter_geometry
from graphics.presenter_layout_graph import PresenterGraphAsset, PresenterGraphSpec, PresenterGraphWindow
from opening_prefix_contract import HeldPrefixInput, PrefixClock, canonical_hash
from opening_prefix_graphs import PresenterGraphLane, presenter_graph_record
from test_presenter_layout_graph import declaration

_ALPHA = re.compile(r"geq=lum_expr='[^']*'")


def normalize(value: object, root: Path) -> object:
    """Normalize only this benchmark root, never source hashes or numeric controls."""
    if type(value) is str:
        return value.replace(str(root), "<TEST-ROOT>")
    if type(value) is list:
        return [normalize(item, root) for item in value]
    if type(value) is dict:
        return {key: normalize(item, root) for key, item in value.items()}
    return value


def _command(report: dict, stage: str) -> list[str]:
    """Require the actual unique completed command for setup or an encode."""
    rows = [row for row in report["commands"] if row["stage"] == stage]
    if len(rows) != 1 or rows[0].get("returncode") != 0 or "error" in rows[0]:
        raise AssertionError(f"comparison lacks one completed {stage} command")
    return rows[0]["argv"]


def command_without_alpha(command: list[str], presenter: bool) -> list[str]:
    """Permit only the one authorized mask expression delta, not other graph edits."""
    result = list(command)
    position = result.index("-filter_complex") + 1
    graph, count = _ALPHA.subn("<AUTHORIZED-ALPHA-EXPRESSION>", result[position])
    if count != (1 if presenter else 0):
        raise AssertionError("comparison found missing/extra mask expressions")
    result[position] = graph
    return result


def compare_metadata(old: dict, new: dict, roots: tuple[Path, Path]) -> dict:
    """Require exact input/tool/encoder/harness equality before accepting any timing."""
    fields = ("scope", "size", "frames", "frameRate", "mediaSeconds", "encoder",
              "sourceAdmission", "cohortLimitSeconds", "processLimitSeconds", "noRetry")
    if any(old.get(key) != new.get(key) for key in fields):
        raise AssertionError("benchmark controls/encoder differ")
    if old.get("status") != "failed" or new.get("status") != "passed" \
            or not old["cleanup"]["exactGroupsAbsent"] or not new["cleanup"]["exactGroupsAbsent"]:
        raise AssertionError("comparison requires retained failed baseline and complete new clean cohort")
    changes = compare_references(old, new, roots)
    for label in ("base", "still", "video"):
        if normalize(_command(old, label + "-setup"), roots[0]) != normalize(_command(new, label + "-setup"), roots[1]):
            raise AssertionError("benchmark generated-input commands differ")
    for label in ("baseline", "still", "video"):
        old_command = normalize(command_without_alpha(_command(old, label + "-encode"), label != "baseline"), roots[0])
        new_command = normalize(command_without_alpha(_command(new, label + "-encode"), label != "baseline"), roots[1])
        if old_command != new_command:
            raise AssertionError("benchmark changed non-alpha graph/encoder/clock arguments")
    return {"sameGeneratedInputBytes": True, "sameToolsAndEncoder": True,
            "sameBenchmarkAndDeclarationCode": True, "codeClosureDifferences": changes,
            "oldCodeClosure": old["references"], "newCodeClosure": new["references"]}


def compare_references(old: dict, new: dict, roots: tuple[Path, Path]) -> list[dict]:
    """Keep tool/media/TEST helper bytes exact; list legitimate production code deltas."""
    references = [{normalize(row["path"], root): (row["sha256"], row["size_bytes"])
                   for row in report["references"]} for report, root in zip((old, new), roots)]
    directory = Path(presenter_layout_geometry.__file__).resolve().parents[1]
    changes = []
    for path in sorted(references[0].keys() | references[1].keys()):
        before, after = references[0].get(path), references[1].get(path)
        if before == after:
            continue
        if not path.startswith(str(directory) + "/") or "/tests/" in path:
            raise AssertionError("benchmark changed generated input, installed tool or TEST declaration/helper bytes")
        changes.append({"path": path, "oldShaSize": before, "newShaSize": after})
    if str(Path(presenter_layout_geometry.__file__).resolve()) not in [row["path"] for row in changes]:
        raise AssertionError("comparison lacks the authorized geometry implementation change")
    return changes


def graph_declaration_record(proof: dict, root: Path, label: str) -> dict:
    """Reconstruct fixed TEST declarations, then match the actual old/new graph hash."""
    observations = proof.get("presenterObservations")
    if type(observations) is not list or len(observations) != 1:
        raise AssertionError("comparison requires exactly one actual selected observation")
    asset = PresenterGraphAsset(**observations[0]["graphAsset"])
    payload = declaration()
    payload.update(assetId=f"TEST-1080p-{label}", enterFrames=5, exitFrames=5)
    payload["mask"]["radiusPx"] = 24
    canvas = PresenterCanvas(1920, 1080, 30, "yuv420p")
    geometry = compile_presenter_geometry(payload, canvas, (0, 30))
    spec = PresenterGraphSpec(canvas, "30000/1001", (PresenterGraphWindow(7, geometry, asset),), "bt709-limited-video")
    sources = {row["path"]: HeldPrefixInput(**row) for row in proof["inputs"]}
    record = presenter_graph_record(PrefixClock(**proof["clock"]), sources[str(root / "base.mp4")],
        PresenterGraphLane((), None, spec, (sources[asset.path],)))
    if canonical_hash(record) != proof["fullGraphHash"] or proof["fullGraphHash"] != proof["openingGraphHash"]:
        raise AssertionError("fixed benchmark declaration does not match actual retained graph proof")
    return normalize(record, root)
