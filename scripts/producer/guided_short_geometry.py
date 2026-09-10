"""Actual ordinary manual-reframe trace bound to held source/base artifacts.

This is mechanical geometry evidence, not subject tracking, a claim that the
crop contains the right subject, or approval. Original source admission and
the live execution/lease remain the caller's independently checked authority.
"""
from __future__ import annotations

import json
import shutil
from fractions import Fraction
from pathlib import Path

from audio.render_audio_authority import run_audio
from cut_preview_io import bound_json, digest, file_hash
from guided_media_profile import SHORT_PROFILE, manual_short_plan, manual_caption_short_plan, manual_short_geometry
from guided_presenter_intake import current_manual_profile as manual_profile
from guided_presenter_profile import presenter_manual_profile, presenter_caption_profile
from guided_opening_inputs import OpeningInputs
from guided_opening_result import held_ref
from media_probe import display_dims
from motion.reframe_split import denorm_crop
from palmier_visual_bootstrap_authority import BOOTSTRAP_AUTHORITY_NAME


def _metadata(path: str, tool: str, rate: str) -> dict:
    """Bounded metadata only; whole media decoding remains the existing reader."""
    value = json.loads(run_audio([tool, "-v", "error", "-select_streams", "v",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,start_pts,sample_aspect_ratio:stream_side_data=rotation",
        "-of", "json", path]))
    rows = value.get("streams", [])
    if len(rows) != 1:
        raise RuntimeError("manual short requires exactly one source/reframe video stream")
    row = rows[0]
    if row.get("sample_aspect_ratio") != "1:1":
        raise RuntimeError("manual short requires explicitly square source/reframe pixels")
    if Fraction(row["r_frame_rate"]) != Fraction(rate) or Fraction(rate) <= 0 \
            or Fraction(row["avg_frame_rate"]) != Fraction(rate) or row.get("start_pts") != 0:
        raise RuntimeError("manual short requires matching zero-origin CFR; frame-rate conversion is unsupported")
    for item in row.get("side_data_list", []):
        if "rotation" in item and item["rotation"] not in (-270, -180, -90, 0, 90, 180, 270):
            raise RuntimeError("manual short source rotation is outside the orthogonal display class")
    width, height = display_dims(row)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise RuntimeError("manual short displayed source dimensions are unsupported")
    return {"displayWidth": width, "displayHeight": height, "stream": row}


def preflight_short_source(inputs: OpeningInputs) -> None:
    """Reject ambiguous displayed geometry before any ordinary source render.

    Caller has already verified exact source-set bytes. The ordinary source-bus
    admission will independently bind the tool/source again; this is no receipt.
    """
    if not manual_profile(inputs.value.get("profile")):
        return
    intent = _manual_intent(inputs)
    sources = [row for row in inputs.documents["manifest"]["sources"] if row.get("id") == intent["sourceId"]]
    if len(sources) != 1:
        raise RuntimeError("manual short source is not the exact independently admitted row")
    tool = shutil.which("ffprobe")
    if tool is None:
        raise RuntimeError("manual short source preflight requires the ordinary ffprobe executable")
    _metadata(sources[0]["path"], str(Path(tool).resolve(strict=True)), inputs.documents["authority"]["frameRate"])


def _trace(receipt: dict, plan: dict, root: Path) -> tuple[dict, Path]:
    """Require the actually executed manual stage, never a caller crop assertion."""
    rows = receipt["stageTrace"]
    if type(rows) is not list or [row.get("stage") for row in rows] != ["audio_channels", "baseline_look", "reframe"]:
        raise RuntimeError("manual short ordinary stage trace is incomplete")
    baseline, reframe = rows[1:]
    if baseline.get("executed") is not False or baseline.get("status") != "not-required" \
            or baseline.get("input") != baseline.get("output") or reframe.get("input") != baseline["output"]:
        raise RuntimeError("manual short has an unqualified pre-crop coordinate transform")
    spec = {"layout": "fill", "crop": plan["reframe"]["crop"]}
    output, spec_path = root / "work/framed.mp4", root / "work/reframe_spec.json"
    if reframe.get("executed") is not True or reframe.get("strategy") != "manual" \
            or reframe.get("output") != str(output) or digest(reframe.get("spec")) != digest(spec):
        raise RuntimeError("manual short actual reframe trace differs from current candidate")
    command = reframe.get("command")
    expected_tail = [str(Path(__file__).parent / "motion/reframe_split.py"), reframe["input"], str(spec_path), str(output)]
    if type(command) is not list or len(command) != 5 or command[1:] != expected_tail:
        raise RuntimeError("manual short actual reframe command is not the ordinary fixed stage")
    if digest(bound_json(spec_path)) != digest(spec):
        raise RuntimeError("manual short executed crop spec changed")
    return reframe, spec_path


def _bootstrap(inputs: OpeningInputs, root: Path) -> tuple[dict, dict, dict]:
    """Hold the actual ordinary receipt and its exact original plan/manifest refs."""
    path = root / BOOTSTRAP_AUTHORITY_NAME
    reference = {"path": str(path), "sha256": file_hash(path)}
    receipt = bound_json(path, reference["sha256"])
    refs = inputs.value["documents"]
    if receipt.get("schemaVersion") != 1 or receipt.get("kind") != "palmier-visual-bootstrap-authority" \
            or receipt.get("plan") != refs["candidatePlan"] or receipt.get("manifest") != refs["manifest"]:
        raise RuntimeError("manual short bootstrap is not the held candidate/source execution")
    from captions.caption_fingerprints import canonical_digest
    payload = {key: value for key, value in receipt.items() if key != "receiptHash"}
    if receipt.get("receiptHash") != canonical_digest("sniper-palmier-visual-bootstrap-v1", payload):
        raise RuntimeError("manual short ordinary bootstrap receipt changed")
    stage, spec = _trace(receipt, inputs.documents["candidatePlan"], root)
    return receipt, reference, {"stage": stage, "spec": {"path": str(spec), "sha256": file_hash(spec)}}


def _framed_reference(receipt: dict, root: Path) -> dict:
    """Project a bounded reference, retaining the rich receipt by its raw SHA.

    The ordinary receipt has nanosecond stat integers outside JS safe numbers;
    it must not be copied into the cross-runtime geometry result or rounded.
    """
    row = receipt["bootstrapArtifact"]
    path = held_ref(row, root, root / "work/framed.mp4")
    return {"path": row["path"], "sha256": row["sha256"],
        "sizeBytes": path.stat().st_size, "videoFrames": row["videoFrames"]}


def capture_short_geometry(inputs: OpeningInputs, root: Path, selection: object, base: dict) -> dict | None:
    """Capture actual displayed geometry once ordinary execution has completed."""
    if not manual_profile(inputs.value.get("profile")):
        return None
    intent = _manual_intent(inputs)
    receipt, reference, trace = _bootstrap(inputs, root)
    bus = selection.master.source_bus
    sources = [row for row in bus.admission.sources if row["id"] == intent["sourceId"]]
    if len(sources) != 1:
        raise RuntimeError("manual short source is not the exact independently admitted row")
    source, rate = sources[0], inputs.documents["authority"]["frameRate"]
    tool = bus.admission.tools["ffprobe"]["path"]
    source_meta = _metadata(source["path"], tool, rate)
    stage = trace["stage"]
    input_path = Path(stage["input"])
    if not input_path.is_relative_to(root / "work"):
        raise RuntimeError("manual short pre-crop picture escaped its ordinary stage root")
    input_ref = {"path": str(input_path), "sha256": file_hash(input_path)}
    input_meta = _metadata(str(input_path), tool, rate)
    if [source_meta[key] for key in ("displayWidth", "displayHeight")] != [input_meta[key] for key in ("displayWidth", "displayHeight")]:
        raise RuntimeError("manual short cut preparation changed the source-coordinate canvas")
    framed = _framed_reference(receipt, root)
    frames = inputs.documents["authority"]["totalFrames"]
    if framed["videoFrames"] != frames or receipt["cutArtifact"]["videoFrames"] != frames \
            or receipt["mediaFacts"]["width"] != 1080 or receipt["mediaFacts"]["height"] != 1920:
        raise RuntimeError("manual short actual reframe canvas/frame count changed")
    return {"schemaVersion": 1, "kind": "guided-manual-short-held-geometry", "profile": inputs.value["profile"],
        "scope": "observed-ordinary-manual-crop-not-subject-tracking-caption-or-approval",
        "candidatePlan": inputs.value["documents"]["candidatePlan"], "manifest": inputs.value["documents"]["manifest"],
        "source": source, "sourceMetadata": source_meta, "inputArtifact": input_ref, "inputMetadata": input_meta,
        "bootstrapReceipt": reference, "specArtifact": trace["spec"], "reframedArtifact": framed,
        "baseArtifact": base, "intent": intent, "frameRate": rate, "totalFrames": frames,
        "resolvedCrop": list(denorm_crop(intent["reframe"]["crop"], input_meta["displayWidth"], input_meta["displayHeight"], "manual short")),
        "captionsBurned": False, "subjectFramingReviewed": False}


def verify_short_geometry(full: dict, inputs: OpeningInputs, root: Path, selection: object) -> None:
    """Reobserve held geometry without rerendering, reauthoring or selecting assets."""
    if not manual_profile(inputs.value.get("profile")):
        if "shortGeometry" in full:
            raise RuntimeError("historical opening cannot acquire newer short geometry")
        return
    if type(full.get("shortGeometryElapsedMs")) is not int or full["shortGeometryElapsedMs"] < 0:
        raise RuntimeError("manual short geometry phase timing is missing or invalid")
    expected = capture_short_geometry(inputs, root, selection, full["base"])
    if digest(full.get("shortGeometry")) != digest(expected):
        raise RuntimeError("manual short held geometry/source/spec evidence changed")


def short_geometry_refs(full: dict, root: Path) -> list[dict]:
    """After strong read, supply exact local dependencies for cheap owner guards."""
    geometry = full.get("shortGeometry")
    if geometry is None:
        return []
    rows = [geometry[key] for key in ("bootstrapReceipt", "specArtifact", "inputArtifact", "reframedArtifact")]
    for row in rows:
        held_ref(row, root)
    return rows


def _manual_intent(inputs: OpeningInputs) -> dict:
    """Keep the old captions-off validator exact; the new class is separately closed."""
    if presenter_manual_profile(inputs.value["profile"]):
        return manual_short_geometry(inputs.documents["candidatePlan"], presenter_caption_profile(inputs.value["profile"]))
    validate = manual_short_plan if inputs.value["profile"] == SHORT_PROFILE else manual_caption_short_plan
    return validate(inputs.documents["candidatePlan"])
