"""Closed current-baseline trace fixtures shared by focused tests."""
from __future__ import annotations

import hashlib

import baseline_trace_validation
from baseline_repeat_validation import PIXEL_IDENTICAL_CLASS
from current_render_calibration_source import RETAINED_ROOT, STORAGE_CLASS
from current_render_graph_contract import canonical_bytes, object_hash
from current_render_oracle import CODEC_FLOOR_POLICY


def current_fixture(mode: str, frames: int, rate: tuple[str, str]) -> dict:
    """Return the minimum classification fixture with plan authority."""
    return {
        "evidenceClass": "current-full-path-baseline",
        "mode": mode,
        "durationFrames": frames,
        "fps": {"numerator": rate[0], "denominator": rate[1]},
        "inputAuthority": {"planSha256": "e" * 64},
    }


def _audit(fixture: dict) -> dict:
    return {
        "mode": fixture["mode"], "overall": "pass", "exitCode": 0,
        "counts": {"pass": 1, "warn": 0, "fail": 0},
        "checks": [{"status": "pass"}],
    }


def _media_tools() -> dict:
    return {
        name: {
            "path": f"/tools/{name}", "sha256": char * 64,
            "version": f"{name} v1",
        }
        for name, char in (("ffmpeg", "1"), ("ffprobe", "2"))
    }


def _qc(fixture: dict, duration: float) -> dict:
    audit = _audit(fixture)
    record = {"authorityHash": "d" * 64, "planHash": "f" * 64}
    return {
        "finalSha256": "d" * 64,
        "auditReport": {
            "sha256": "3" * 64,
            "documentSha256":
                baseline_trace_validation._document_sha256(audit),
            "document": audit,
        },
        "assembledAuthority": {
            "sha256": "4" * 64,
            "recordSha256":
                baseline_trace_validation._document_sha256(record),
            "record": record,
        },
        "renderPlan": {"sha256": "e" * 64, "contentHash": "f" * 64},
        "timelineMap": {
            "sha256": "5" * 64, "outputDuration": duration,
        },
    }


def current_output(fixture: dict, video_hash: str = "a" * 64) -> dict:
    """Return one fully QC-bound decoded output observation."""
    short = fixture["mode"] == "short"
    rate = (
        f"{fixture['fps']['numerator']}/{fixture['fps']['denominator']}")
    duration = (
        fixture["durationFrames"] * int(fixture["fps"]["denominator"])
        / int(fixture["fps"]["numerator"])
    )
    media = {
        "video": {
            "width": 1080 if short else 1920,
            "height": 1920 if short else 1080,
            "rFrameRate": rate, "avgFrameRate": rate,
            "decodedFrames": fixture["durationFrames"],
            "duration": f"{duration:.6f}",
        },
        "audio": {
            "sampleRate": 48000, "channels": 2,
            "duration": f"{duration:.6f}",
        },
        "fullDecode": {
            "videoSha256": video_hash,
            "audioPcmS16le48000StereoSha256": "b" * 64,
            "audioPcmBytes": 400, "audioSamplesPerChannel": 100,
        },
        "tools": _media_tools(),
        "qc": _qc(fixture, duration),
    }
    return {"status": "present", "sha256": "d" * 64, "media": media}


def set_output_sha(output: dict, digest: str) -> None:
    """Keep output/QC/assembled hashes mutually bound after a test mutation."""
    output["sha256"] = digest
    output["media"]["qc"]["finalSha256"] = digest
    authority = output["media"]["qc"]["assembledAuthority"]
    authority["record"]["authorityHash"] = digest
    authority["recordSha256"] = baseline_trace_validation._document_sha256(
        authority["record"])


def _oracle_media(runs: list[dict], index: int, picture: str,
                  facts: dict) -> dict:
    return {
        "path": f"/media/run-{index}.mp4",
        "fileSha256": runs[index]["outputs"][0]["sha256"],
        "sizeBytes": 100,
        "pictureFrameMd5Sha256": picture,
        "pcmSha256": "8" * 64,
        "pcmBytes": 800,
        "streamFacts": facts,
    }


def _calibration(toolchain: dict) -> dict:
    digest = "7" * 64
    document = {
        "schemaVersion": 1,
        "policy": CODEC_FLOOR_POLICY,
        "policyHash": object_hash(CODEC_FLOOR_POLICY),
        "passed": True,
        "observed": {"pairCount": 3},
        "pairs": [{}, {}, {}],
        "sourceFiles": {"/source.py": "6" * 64},
        "source": {
            "path": str(
                RETAINED_ROOT / "sha256" / "77" / f"{digest}.media"),
            "sha256": digest, "sizeBytes": 100,
            "storageClass": STORAGE_CLASS,
        },
        "tools": toolchain,
    }
    document["receiptHash"] = object_hash(document)
    return document


def repeat_equivalence(
    fixture: dict,
    runs: list[dict],
    exact: bool = False,
) -> dict:
    """Return an exact or calibrated non-pixel oracle wrapper."""
    video = runs[0]["outputs"][0]["media"]["video"]
    facts = {
        "streamTypes": ["video", "audio"],
        "video": {
            "width": video["width"], "height": video["height"],
            "pixelFormat": "yuv420p", "frameRate": video["rFrameRate"],
            "decodedFrames": fixture["durationFrames"],
        },
        "audio": {"sampleRate": 48000, "channels": 2},
    }
    toolchain = {
        name: {"path": f"/tools/{name}", "sha256": char * 64}
        for name, char in (
            ("ffmpeg", "1"), ("ffprobe", "2"), ("oracle", "3"))
    }
    receipt = _oracle_receipt({
        "fixture": fixture,
        "runs": runs,
        "facts": facts,
        "toolchain": toolchain,
        "exact": exact,
    })
    calibration = _calibration(toolchain)
    return {
        "schemaVersion": 1,
        "classification": (
            PIXEL_IDENTICAL_CLASS if exact
            else CODEC_FLOOR_POLICY["pictureClaim"]),
        "receiptPath": ".baseline-repeat-evidence/test/repeat-oracle-v1.json",
        "receiptSha256": hashlib.sha256(
            canonical_bytes(receipt) + b"\n").hexdigest(),
        "receipt": receipt,
        "calibrationAuthority": {
            "path": (
                "docs/producer/command-driven-editing/contracts/"
                "current-render-codec-floor-calibration-v1.json"),
            "sha256": hashlib.sha256(
                canonical_bytes(calibration) + b"\n").hexdigest(),
            "documentSha256":
                baseline_trace_validation._document_sha256(calibration),
            "document": calibration,
        },
        "error": None,
    }


def _oracle_receipt(context: dict) -> dict:
    fixture = context["fixture"]
    runs = context["runs"]
    facts = context["facts"]
    toolchain = context["toolchain"]
    exact = context["exact"]
    left = _oracle_media(runs, 0, "4" * 64, facts)
    right = _oracle_media(runs, 1, "4" * 64 if exact else "5" * 64, facts)
    receipt = {
        "schemaVersion": 1,
        "kind": "current-render-forced-full-oracle",
        "policy": CODEC_FLOOR_POLICY,
        "policyHash": object_hash(CODEC_FLOOR_POLICY),
        "toolchain": toolchain, "incremental": left, "forcedFull": right,
        "pictureComparison": {
            "method": "exact-framemd5" if exact else "full-frame-ssim",
            "pixelIdentical": exact, "codecFloorEquivalent": True,
            "metrics": None if exact else {
                "comparedFrames": fixture["durationFrames"],
                "meanSsim": 0.997, "minimumFrameSsim": 0.991,
                "minimumFrameIndex": 2,
            },
            "claim": CODEC_FLOOR_POLICY["pictureClaim"],
        },
        "decodedAudioMatch": True, "streamFactsMatch": True,
        "byteIdentical": left["fileSha256"] == right["fileSha256"],
        "passed": True,
    }
    receipt["receiptHash"] = object_hash(receipt)
    return receipt
