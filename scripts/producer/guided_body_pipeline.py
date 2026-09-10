"""Current body adapter closure in the original immutable producer snapshot.

Original opening execution metadata is not resealed or relabeled as body work.
This additional closure proves only the code actually invoked for this new
mechanical attempt; a pipeline hash is neither approval nor runtime evidence.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash
from guided_body_execution import BodyHeldFile, hold_body_file
from guided_opening_inputs import OpeningInputs
from guided_opening_pipeline import observe_pipeline
from render_effect_discovery import local_python_import_closure


def _body_closure(inputs: OpeningInputs) -> list[dict]:
    """Every new fixed media/read/cleanup adapter must already be in the held lock."""
    producer = Path(__file__).resolve().parent
    root = producer.parents[1]
    pipeline = inputs.value["pipeline"]
    lock = bound_json(Path(pipeline["lockPath"]), pipeline["lockSha256"])
    expected = {row["path"]: row["hash"] for row in lock["files"]}
    entrypoints = [producer / f"guided_body_{name}.py" for name in ("media", "read", "cleanup")]
    files = local_python_import_closure(entrypoints)
    result = []
    for path in sorted(set(files)):
        logical = str(path.relative_to(root))
        observed = file_hash(path)
        if expected.get(logical) != observed:
            raise RuntimeError(f"body invoked source is absent or changed in original pinned closure: {logical}")
        result.append({"path": logical, "sha256": observed})
    return result


def observe_body_pipeline(inputs: OpeningInputs, original_result: dict) -> dict:
    """Keep old source/tool proof exact while admitting the additional body code."""
    opening = observe_pipeline(inputs)
    if digest(opening) != digest(original_result["pipeline"]):
        raise RuntimeError("body original opening source/tool closure is stale")
    return {"schemaVersion": 1, "kind": "guided-body-executed-pipeline",
        "scope": "original-opening-plus-current-body-code-not-approval",
        "opening": opening, "bodyExecutionClosure": _body_closure(inputs)}


def hold_body_dependencies(inputs: OpeningInputs, pipeline: dict) -> tuple[BodyHeldFile, ...]:
    """Capture control/template/code identities once for cheap publication guards."""
    producer = Path(__file__).resolve().parent
    root = producer.parents[1]
    refs = [(Path(row["path"]), row["sha256"]) for row in inputs.value["documents"].values()]
    refs.append((inputs.path, inputs.sha256))
    refs.extend((root / row["path"], row["sha256"]) for row in pipeline["bodyExecutionClosure"])
    refs.extend((root / row["path"], row["sha256"]) for row in pipeline["opening"]["executionClosure"])
    refs.extend((Path(row["path"]), row["sha256"]) for row in pipeline["opening"]["tools"].values())
    lock = inputs.value["pipeline"]
    refs.append((Path(lock["lockPath"]), lock["lockSha256"]))
    seen, result = {}, []
    for path, sha in refs:
        if path in seen and seen[path] != sha:
            raise RuntimeError("body dependency has conflicting held byte identities")
        if path not in seen:
            result.append(hold_body_file(path, sha, 64 * 1024 * 1024))
            seen[path] = sha
    return tuple(result)
