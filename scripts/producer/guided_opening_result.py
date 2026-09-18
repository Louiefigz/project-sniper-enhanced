"""Read-only exact-artifact checks for an actually returned private opening.

These functions do not authenticate an invocation. The caller must hold the
successful worker's raw result hash, not compute authority from this directory.
No render, repair, normalization, publication or approval occurs here.
"""
from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from audio.program_audio_clock import exact_aac_audio_clock
from audio.program_master_excerpt import sample_range
from cut_preview_io import bound_json, digest, file_hash
from guided_opening_claim import _canonical_path
from guided_opening_graphic_proof import verify_graphics_unchanged
from guided_opening_inputs import closed, hash_value
from guided_opening_mux import _measure
from guided_opening_picture import observe_picture
from guided_caption_profile import caption_profile


def held_ref(value: dict, root: Path, expected: Path | None = None) -> Path:
    """Read only an exact regular artifact below the owned execution directory."""
    if type(value) is not dict or type(value.get("path")) is not str:
        raise RuntimeError("opening result artifact reference is malformed")
    path = _canonical_path(value["path"])
    if not path.is_relative_to(root) or path == root or (expected is not None and path != expected):
        raise RuntimeError("opening result artifact escaped its exact owned location")
    if file_hash(path) != hash_value(value.get("sha256")):
        raise RuntimeError("opening result artifact bytes changed")
    if "sizeBytes" in value and (type(value["sizeBytes"]) is not int or path.stat().st_size != value["sizeBytes"]):
        raise RuntimeError("opening result artifact size differs")
    return path


def _picture(row: dict, context: tuple) -> None:
    """Reobserve complete picture decode and exact global-range clock facts."""
    root, authority, tools, span = context
    path = held_ref(row, root)
    if path.name not in {"core-picture.mp4", "review-picture.mp4"} or path.parent != root:
        raise RuntimeError("opening picture is not a range artifact")
    expected = authority["frameRate"], span["endFrameExclusive"] - span["startFrame"], (
        authority["target"]["width"], authority["target"]["height"])
    observed = observe_picture(path, expected, tools)
    if set(row) != set(observed) | {"startFrame", "endFrameExclusive", "compositorPasses"} \
            or any(row[key] != value or type(row[key]) is not type(value) for key, value in observed.items()) \
            or any(row[key] != value for key, value in span.items()) \
            or type(row["compositorPasses"]) is not int or row["compositorPasses"] < 1:
        raise RuntimeError("opening picture readback differs from held range proof")


def _media(row: dict, context: tuple) -> None:
    """Recheck exact native picture copy, actual AAC clock and full audio decode."""
    root, picture, pcm, tools = context
    keys = {"path", "sha256", "sizeBytes", "picture", "audioClock", "audioMeasurement", "sourcePcmSha256",
        "audiblePathAacEncodes", "startFrame", "endFrameExclusive", "startSample", "endSampleExclusive"}
    closed(row, keys, "opening encoded range")
    path = held_ref(row, root)
    if path.parent != root or path.name not in {"core.mp4", "review.mp4"}:
        raise RuntimeError("opening encoded range has the wrong fixed output role")
    if any(type(row[key]) is not int or row[key] != pcm[key] for key in (
            "startFrame", "endFrameExclusive", "startSample", "endSampleExclusive")) \
            or type(row["audiblePathAacEncodes"]) is not int or row["audiblePathAacEncodes"] != 1 \
            or row["sourcePcmSha256"] != pcm["pcmSha256"]:
        raise RuntimeError("opening encoded range differs from full-master PCM authority")
    source = observe_picture_source(picture["path"], float(Fraction(picture["frames"], 1)
                                    / Fraction(picture["frameRate"])), picture["sha256"])
    actual = {"picture": verify_picture_copy(source, str(path)),
        "audioClock": exact_aac_audio_clock(str(path), tools["ffprobe"]["path"], pcm["samples"]),
        "audioMeasurement": _measure(path)}
    if any(digest(row[key]) != digest(value) for key, value in actual.items()):
        raise RuntimeError("opening encoded media measurement differs from held execution")
    held_ref(row, root)


def read_ranges(record: dict, audio: dict, context: tuple[Path, dict, dict], presenter: object = None) -> None:
    """Validate core/review absolute endpoints, ordering and unchanged A/V artifacts."""
    root, authority, tools = context
    fields, check = _presenter_fields(record, presenter, [audio, str(root), authority, tools])
    pictures = closed(record["pictures"], {"policy", "ranges", "candidateOrder", "executedOrder", "orderPolicy",
        "placementScope"} | ({"captionLayers"} if caption_profile(record.get("profile")) else set()) | fields, "opening picture result")
    closed(pictures["ranges"], {"core", "review"}, "opening picture ranges")
    closed(record["media"], {"core", "review"}, "opening media ranges")
    if pictures["policy"] != "global-composition-then-half-open-frame-trim-v1" \
            or pictures["orderPolicy"] != "ordinary-outStart-ascending-stable-candidate-ties" \
            or pictures["placementScope"] != "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof":
        raise RuntimeError("opening picture policy or proof scope differs")
    completed = set()
    for name in ("core", "review"):
        span = authority[name]
        expected = sample_range((span["startFrame"], span["endFrameExclusive"]), (
            authority["frameRate"], authority["totalFrames"]))
        if any(type(audio[name][key]) is not type(value) or audio[name][key] != value for key, value in expected.items()):
            raise RuntimeError("opening audio is not the exact authority range")
        _read_pair(record, audio[name], (root, authority, tools, span, name), completed)
    if presenter is not None:
        check()
        presenter.verify(record)
        check()


def _presenter_fields(record: dict, lane: object,
                      related: object) -> tuple[set[str], Callable[[], None] | None]:
    """New picture fields require a typed original read scope, never a result flag."""
    from guided_presenter_opening_read import PresenterOpeningReadLane
    from guided_presenter_intake import is_presenter_profile
    from guided_presenter_profile import presenter_caption_profile

    profile = record.get("profile")
    if not is_presenter_profile(profile):
        if lane is not None:
            raise RuntimeError("legacy opening cannot acquire a presenter read lane")
        return set(), None
    if type(lane) is not PresenterOpeningReadLane:
        raise RuntimeError("presenter opening requires its actual original read context")
    check = lane.hold([record, related])
    check()
    lane.verify(record)
    check()
    fields = {"presenterLayers"} | ({"presenterCaptionClearance"} if presenter_caption_profile(profile) else set())
    return fields, check


def _read_pair(record: dict, pcm: dict, context: tuple, completed: set) -> None:
    """Deduplicate only identical held picture/media/PCM/range combinations."""
    root, authority, tools, span, name = context
    picture, media = record["pictures"]["ranges"][name], record["media"][name]
    identity = digest([picture, media, pcm, span])
    if identity in completed:
        return
    _picture(picture, (root, authority, tools, span))
    _media(media, (root, picture, pcm, tools))
    completed.add(identity)


def read_graphics(record: dict, rows: list[dict], root: Path) -> None:
    """Bind each actual proof/archive/request to its original exact candidate order."""
    evidence = record["graphics"]
    if type(evidence) is not list or len(evidence) != len(rows):
        raise RuntimeError("opening graphic proofs do not cover the exact selected entries")
    for proof, row in zip(evidence, rows):
        _graphic(proof, row, root)
    expected_order = [row["graphicId"] for row in rows]
    executed_order = [row["graphicId"] for row in sorted(rows, key=lambda row: float(row["entry"]["outStart"]))]
    if record["pictures"]["candidateOrder"] != expected_order or record["pictures"]["executedOrder"] != executed_order:
        raise RuntimeError("opening graphic candidate/executed ordering differs")
    verify_graphics_unchanged(evidence)


def _graphic(proof: dict, row: dict, root: Path) -> None:
    """Reject redirected proof refs before opening any dependent artifact."""
    attempt = root / "graphics/attempts" / f"graphic-{row['order']}"
    if proof.get("candidateOrder") != row["order"] or proof.get("graphicId") != row["graphicId"] \
            or proof.get("workerCleanupObserved") is not True:
        raise RuntimeError("opening graphic identity or worker cleanup proof differs")
    request_path = held_ref({"path": proof["requestPath"], "sha256": proof["requestSha256"]},
                           root, attempt / "execution-request.json")
    request = bound_json(request_path, proof["requestSha256"])
    intent = request["intent"]
    if intent["entryHash"] != row["entryHash"] or digest(intent["entry"]) != digest(row["entry"]) \
            or intent["startFrame"] != row["startFrame"] or intent["endFrameExclusive"] != row["endFrameExclusive"]:
        raise RuntimeError("opening graphic original entry/frame intent differs")
    asset = held_ref(proof["actualAsset"], attempt / "cache")
    for key, suffix in (("inputArchive", ".input.tar"), ("proofSidecar", ".proof.json"), ("runtimeSidecar", ".runtime.json")):
        held_ref(proof[key], root, Path(str(asset) + suffix))
    if proof["resourceLedgerPath"] != str(attempt / "resource-ledger.json"):
        raise RuntimeError("opening graphic ledger is outside its exact claimed order")


def check_held_artifacts(record: dict, audio: dict, root: Path) -> None:
    """Rehash the fixed dependent artifact set without trusting a recursive walk."""
    refs = [record["audio"], record["fullProgram"]["base"], *record["fullProgram"]["receipts"].values(),
            *record["pictures"]["ranges"].values(), *record["media"].values(), audio["core"], audio["review"]]
    for row in record["graphics"]:
        refs.extend(row[key] for key in ("actualAsset", "inputArchive", "proofSidecar", "runtimeSidecar"))
        refs.append({"path": row["requestPath"], "sha256": row["requestSha256"]})
        if "captionLayoutObservation" in row:
            refs.append(row["captionLayoutObservation"]["observation"])
    seen = set()
    for ref in refs:
        identity = ref["path"], ref["sha256"]
        if identity not in seen:
            held_ref(ref, root)
            seen.add(identity)
