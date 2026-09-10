"""Read-only revalidation of the explicitly reviewed six current probe rows.

This does not accept arbitrary self-hashed old evidence or failed media rows.
The original budget-stopped attempt stays immutable. Revalidation is not a
fresh renderer execution and is disclosed separately in the continuation.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cut_preview_io import bound_json, file_hash, read_bytes, write_new
from graphics.comp_catalog_probe import _measure_artifact, static_probe
from graphics.asset_proof import AssetProofRequest, _probe, _validate_stream, _full_decode, _visible_alpha
from graphics.frame_quantization import hyperframes_duration, placement_frame_span
from graphics.template_contract import composition_dimensions
from headless.container_io import CompositionInput, create_snapshot
from headless.runtime_receipt import validate_runtime_attestation

COHORT_SHA256 = "0283c3778a4c780c6ceeadadf5634a1d0c589d8ea515549a7f7baa950b89e20b"
SOURCE_SHA256 = "f8ec06172fd6a6c2e64e6f30a00020cd11e27b64b60d147489c05962e28634de"
RUNNER_SHA256 = "127e15ac7165a55d611b5f4bf47ea7a74f9b3f8c621c43fb3e405f853cc8d1c3"
_SECOND_COHORT = "47a1dca1d1fc67c2ba65118fbc8e7fb3baf674e6722a55b2c513b103eb37c818"
_APPROVED = {
    COHORT_SHA256: (SOURCE_SHA256, RUNNER_SHA256, 6),
    _SECOND_COHORT: ("ff53ad250aa197367f1216ed735fdb1458357dd472d4b8d446ed1c8239809983",
        "546712d21ba5cb797ce16515502683061b8ffe74c5b9c802c3a6db8ce1403b8b", 8),
}


def _source_binding(previous: dict, current: dict) -> None:
    if previous["renderBuild"] != current["renderBuild"] or previous["motionSourceDigest"] != current["motionSourceDigest"]:
        raise RuntimeError("partial capability render/source closure is no longer current")
    old = previous["measurementSources"]
    expected = {"graphics/comp_capability_refresh.py", "graphics/comp_catalog_probe.py",
                "color/deadline.py", "planner/graphics_anchors.py"}
    allowed = expected | {"graphics/comp_capability_resume.py", "graphics/comp_capability_timing.py"}
    if set(old) not in (expected, allowed) or old["graphics/comp_capability_refresh.py"] not in {row[1] for row in _APPROVED.values()}:
        raise RuntimeError("partial capability runner is not the independently reviewed predecessor")
    if any(current["measurementSources"][key] != old[key] for key in expected - {"graphics/comp_capability_refresh.py"}):
        raise RuntimeError("partial capability measurement code changed")


def _header(root: Path, current: dict) -> tuple:
    held = file_hash(root / "cohort.json")
    if held not in _APPROVED:
        raise RuntimeError("capability predecessor is not an explicitly reviewed immutable attempt")
    source_hash, runner_hash, count = _APPROVED[held]
    cohort = bound_json(root / "cohort.json", held)
    source = bound_json(root / "source-before.json", source_hash)
    _source_binding(source, current)
    if len(cohort["probes"]) != count or source["measurementSources"]["graphics/comp_capability_refresh.py"] != runner_hash:
        raise RuntimeError("capability predecessor row/runner binding changed")
    return cohort, source, held


def _snapshot(entry: dict, source: str, receipt: dict, state: dict) -> None:
    frames = placement_frame_span(entry["outStart"], entry["outEnd"], 30)
    duration = hyperframes_duration(frames, 30)
    composition = CompositionInput(f"compositions/{entry['kind']}.html", source, {"fps": "30"}, duration)
    with tempfile.TemporaryDirectory(prefix="capability-resume-seal-") as temporary:
        sealed = create_snapshot(state["renderBuild"]["pipelineRoot"], composition, entry["spec"], temporary)
        if sealed.sha256 != receipt["snapshotSha256"] or list(sealed.manifest) != receipt["snapshotManifest"]:
            raise RuntimeError("partial probe does not bind exact current source/spec/duration")


def _media(row: dict, entry: dict, source: str, state: dict) -> dict:
    media = Path(row["mediaPath"])
    if file_hash(media) != row["mediaSha256"]:
        raise RuntimeError("partial capability media changed")
    proof = bound_json(Path(str(media) + ".proof.json"))
    receipt = proof["runtimeAttestation"]
    raw_runtime = bound_json(Path(str(media) + ".runtime.json"))
    if {key: value for key, value in receipt.items() if key != "retainedInputArchive"} != raw_runtime \
            or proof["asset"]["sha256"] != row["mediaSha256"]:
        raise RuntimeError("partial persisted proof/runtime/media bindings disagree")
    validate_runtime_attestation(receipt, str(media), row["mediaSha256"], state["renderBuild"]["imageId"])
    if receipt["containerAfterOutput"]["Name"] != "/" + row["containerName"]:
        raise RuntimeError("partial probe has another owned runtime")
    _snapshot(entry, source, receipt, state)
    command = ["render", "/scratch/project/motion", "-c", f"compositions/{entry['kind']}.html",
        "--format", "mov", "--variables-file", "/scratch/project/request/variables.json", "-o",
        "/output/render.mov", "--fps", "30", "--quality", "high", "--workers", "1",
        "--no-browser-gpu", "--strict", "--strict-variables", "--json"]
    if receipt["containerBeforeOutput"]["Args"] != command or receipt["containerAfterOutput"]["Args"] != command:
        raise RuntimeError("partial runtime CLI does not bind the exact requested kind/rate")
    duration = hyperframes_duration(placement_frame_span(entry["outStart"], entry["outEnd"], 30), 30)
    request = AssetProofRequest(str(media), entry, "mov", composition_dimensions(source), duration,
                                media.stem, expected_fps=30, require_terminal_clear=False)
    streams = _probe(str(media))["streams"]
    if len(streams) != 1:
        raise RuntimeError("partial capability has unexpected media streams")
    _, _, _, frames = _validate_stream(streams[0], request)
    _full_decode(str(media))
    _visible_alpha(str(media))
    measured = {"probeDurationS": entry["outEnd"]}
    _measure_artifact(measured, str(media), frames, None)
    if measured != row["measurements"] or file_hash(media) != row["mediaSha256"]:
        raise RuntimeError("partial capability decoded measurements changed")
    return measured


def resume_rows(request: tuple, state: dict, entries: dict) -> tuple[dict, list]:
    """Revalidate exact approved predecessor and preserve links to every raw artifact."""
    previous_root, output = request
    previous = Path(previous_root).resolve(strict=True)
    cohort, before, held = _header(previous, state)
    sources = {previous: before}
    if held == _SECOND_COHORT:
        ancestor = Path(cohort["resumeDirectory"]).resolve(strict=True)
        parent, parent_source, parent_hash = _header(ancestor, state)
        if parent_hash != COHORT_SHA256 or cohort["probes"][:6] != parent["probes"]:
            raise RuntimeError("capability continuation does not retain the exact six-row lineage")
        sources[ancestor] = parent_source
    rows = cohort["probes"]
    if len({row["kind"] for row in rows}) != len(rows) or any(row.get("passed") is not True for row in rows):
        raise RuntimeError("partial capability set is not the reviewed successful rows")
    comps, evidence = {}, []
    for row in rows:
        directory = Path(row["mediaPath"]).parent.parent
        if directory.parent not in sources or directory.name != row["kind"]:
            raise RuntimeError("partial capability directory is outside its exact lineage")
        request_value = bound_json(directory / "request.json")
        entry, source = entries[row["kind"]]
        if request_value["entry"] != entry or request_value["sourceState"] != sources[directory.parent] or bound_json(directory / "result.json") != row:
            raise RuntimeError("partial request/result is not its exact recorded binding")
        if request_value["fps"] != "30" or request_value["containerName"] != row["containerName"] \
                or request_value["imageId"] != state["renderBuild"]["imageId"]:
            raise RuntimeError("partial requested runtime differs from its exact observation")
        if Path(row["mediaPath"]).parent != directory / "cache":
            raise RuntimeError("partial media escaped its recorded probe")
        ledger = bound_json(directory / "resource-ledger.json")
        if len(ledger["resources"]) != 1 or ledger["resources"][0]["containerName"] != row["containerName"] or ledger["resources"][0]["state"] != "REMOVED":
            raise RuntimeError("partial probe cleanup is not proved")
        measured = _media(row, entry, source, state)
        comps[row["kind"]] = {**static_probe(row["kind"], source), **measured}
        evidence.append({"kind": row["kind"], "freshRender": False,
            "sourceDirectory": str(directory), "files": {str(path.relative_to(directory)): file_hash(path)
                for path in directory.rglob("*") if path.is_file() and path.stat().st_size > 0}})
    for path in sources:
        _header(path, state)
    write_new(Path(output) / "resumed-evidence.json", {"cohortSha256": held,
        "scope": "reviewed-current-row-lineage-revalidated-not-rerendered", "rows": evidence})
    return comps, rows
