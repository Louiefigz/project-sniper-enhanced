"""Explicit admission and same-run authority for ordinary source-float audio."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.channel_normalization import ChannelAuthority, ChannelRequest, ChannelTools, SourceIdentity
from audio.channel_normalization_receipt import verify_channel_receipt
from cross_runtime_canonical_json import canonical_compact_json
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256, plan_content_hash
from ingest_execution_authority import execution_media_authority_entries
from palmier.process_deadline import process_timeout
from render_effect_discovery import local_python_import_closure
from render_effect_registry import RenderEffectError, validate_root_fields

SOURCE_FLOAT_POLICY = "source-float-v1"
SOURCE_FLOAT_POLICY_V2 = "source-float-v2"
LEGACY_AUDIO_POLICY = "legacy-v1"


@dataclass(frozen=True)
class AudioAdmission:
    """Held exact source, plan and executable facts, not a reusable path cache."""

    plan_hash: str
    manifest_path: str
    manifest_hash: str
    source_set_digest: str
    sources: tuple[dict, ...]
    tools: dict
    code: tuple[dict, ...]
    policy: str = SOURCE_FLOAT_POLICY
    audio_input_hash: str | None = None
    manifest_source_hash: str | None = None


def _finishing_reason(plan: dict, policy: str) -> str | None:
    """v2 finishes dialogue/SFX in the shared program master; v1 still refuses them."""
    if policy == SOURCE_FLOAT_POLICY_V2:
        from audio.program_finish_contract import finishing_reason
        reason = finishing_reason(plan)
        return f"{policy} rejects {reason}" if reason else None
    if plan.get("audioEnhance") or plan.get("audioGain"):
        return f"{policy} has not qualified enhancement or gain windows"
    if any(row.get("sfx") for row in plan.get("transitions") or []):
        return f"{policy} has not qualified authored SFX"
    return None


def audio_policy_reason(plan: dict, policy: str = SOURCE_FLOAT_POLICY) -> str | None:
    """Report the first unsupported or invalid capability without rewriting user intent."""
    try:
        validate_root_fields("plan", plan)
    except RenderEffectError as error:
        return str(error)
    cuts = plan.get("cutTrack") or []
    if not cuts or any(type(row.get("speed", 1)) not in {int, float}
                       or row.get("speed", 1) != 1 for row in cuts):
        return f"{policy} requires source speed 1 only"
    finishing = _finishing_reason(plan, policy)
    if finishing:
        return finishing
    if policy != SOURCE_FLOAT_POLICY_V2 and (plan.get("music") or {}).get("enabled"):
        return "source-float-v1 has not qualified music/ducking integration"
    if policy != SOURCE_FLOAT_POLICY_V2 and plan.get("captionsTrack") \
            and (plan.get("captions") or {}).get("burn", True):
        return "source-float-v1 has not qualified post-master caption-shard mutation"
    return None


def source_audio_input_hash(plan: dict) -> str:
    """Version the exact consumed source-cut inputs, retaining whole origin separately."""
    return content_hash({"domain": "ordinary-source-float-input-v2",
        "cutTrack": plan.get("cutTrack"),
        "target": {key: plan.get("target", {}).get(key)
                   for key in ("mode", "fps", "width", "height")}})


def source_manifest_hash(manifest: dict) -> str:
    """Bind source media and complete admission, independent of music UI selection."""
    return content_hash({"domain": "ordinary-source-manifest-v2",
        "sources": manifest.get("sources"), "sourceSetAdmission": manifest.get("sourceSetAdmission")})


def run_audio(command: list[str]) -> bytes:
    """Run an owned media command, rejecting decoder errors and a failed exit."""
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            check=False, timeout=process_timeout())
    if result.returncode:
        raise RuntimeError("source-float audio command failed: "
                           + result.stderr[-1200:].decode("utf-8", "replace"))
    return result.stdout


def _code_files(policy: str = SOURCE_FLOAT_POLICY) -> tuple[dict, ...]:
    """Bind the adapter's byte-changing code, not unrelated concurrent workers."""
    root = Path(__file__).resolve().parents[1]
    entries = [root / "render.py"]
    if policy == SOURCE_FLOAT_POLICY_V2:
        entries.extend((root / "assemble.py", root / "audio/program_master_bus.py"))
    paths = local_python_import_closure(entries)
    paths.append(root.parents[1] / "schemas/producer/channel-normalization-receipt-v1.schema.json")
    return tuple({"path": str(path), "sha256": file_sha256(str(path))}
                 for path in sorted(set(paths)))


def _source_fact(row: dict, ffprobe: str) -> dict:
    """Admit actual zero-origin CFR sources, with explicit first-audio absence."""
    path = row["path"]
    value = json.loads(run_audio([ffprobe, "-v", "error", "-show_streams",
                                 "-of", "json", path]))
    videos = [item for item in value["streams"] if item.get("codec_type") == "video"]
    audios = [item for item in value["streams"] if item.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise RuntimeError("source-float requires exactly one source picture stream")
    picture = videos[0]
    if Fraction(picture["r_frame_rate"]) <= 0 \
            or Fraction(picture["r_frame_rate"]) != Fraction(picture["avg_frame_rate"]) \
            or int(picture.get("start_pts", -1)) != 0:
        raise RuntimeError("source-float requires zero-origin CFR source picture")
    audio = audios[0] if audios else None
    if audio is not None and (audio.get("channels") not in {1, 2}
            or audio.get("sample_rate") not in {"44100", "48000"}
            or int(audio.get("start_pts", -1)) != 0):
        raise RuntimeError("source-float requires zero-origin mono/stereo 44.1/48 kHz audio")
    return {"id": row["id"], "path": path, "sha256": row["sourceSha256"],
            "audioStreamIndex": audio["index"] if audio else None,
            "audioSampleRate": int(audio["sample_rate"]) if audio else None}


def admit_audio(plan: dict, manifest: dict, options: tuple[str, bool]) -> AudioAdmission | None:
    """Resolve an explicit fresh capability before producing ordinary media."""
    policy, resume = options
    if policy == LEGACY_AUDIO_POLICY:
        return None
    if policy not in {SOURCE_FLOAT_POLICY, SOURCE_FLOAT_POLICY_V2}:
        raise RuntimeError("unknown ordinary audio clock policy")
    reason = audio_policy_reason(plan, policy)
    if reason or resume:
        raise RuntimeError(reason or "source-float-v1 requires fresh execution; resume is not qualified")
    manifest_path = manifest.get("_path")
    if not isinstance(manifest_path, str) or not execution_media_authority_entries(
            plan, manifest, manifest_path):
        raise RuntimeError("source-float requires current source-set admission")
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if not path:
            raise RuntimeError(f"source-float requires {name}")
        path = os.path.realpath(path)
        tools[name] = {"path": path, "sha256": file_sha256(path)}
    sources = tuple(_source_fact(row, tools["ffprobe"]["path"])
                    for row in manifest["sources"])
    admission = AudioAdmission(plan_content_hash(plan), manifest_path,
        file_sha256(manifest_path), manifest["sourceSetAdmission"]["sourceSetDigest"],
        sources, tools, _code_files(policy), policy,
        source_audio_input_hash(plan) if policy == SOURCE_FLOAT_POLICY_V2 else None,
        source_manifest_hash(manifest) if policy == SOURCE_FLOAT_POLICY_V2 else None)
    assert_admission(admission, plan)
    return admission


def assert_admission(admission: AudioAdmission, plan: dict) -> None:
    """Rehash all admitted source bytes, including silent/unused source rows."""
    if not _input_authority_current(admission, plan):
        raise RuntimeError("source-float plan or manifest changed during execution")
    if any(os.path.realpath(shutil.which(name) or "") != item["path"]
           for name, item in admission.tools.items()):
        raise RuntimeError("source-float active media executable changed")
    for row in (*admission.sources, *admission.tools.values(), *admission.code):
        path = Path(row["path"])
        if path.is_symlink() or not path.is_file() \
                or file_sha256(str(path)) != row["sha256"]:
            raise RuntimeError("source-float admitted bytes changed during execution")


def _input_authority_current(admission: AudioAdmission, plan: dict) -> bool:
    """V1 stays whole-plan-bound; only new v2 facts have a separate reuse domain."""
    if admission.policy != SOURCE_FLOAT_POLICY_V2:
        return plan_content_hash(plan) == admission.plan_hash \
            and file_sha256(admission.manifest_path) == admission.manifest_hash
    with open(admission.manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    return audio_policy_reason(plan, admission.policy) is None \
        and source_audio_input_hash(plan) == admission.audio_input_hash \
        and source_manifest_hash(manifest) == admission.manifest_source_hash


def channel_authorities(admission: AudioAdmission, receipts: list[dict]) -> dict:
    """Reuse exact same-cut channel observations, never an arbitrary JSON decision."""
    expected = {row["path"]: row for row in admission.sources}
    result = {}
    for item in receipts:
        receipt = verify_channel_receipt(item["receipt"])
        source, observed_tools = receipt["source"], receipt["tools"]
        path = source["path"]
        row = expected.get(path)
        if type(item.get("sourcePath")) is not str or os.path.realpath(item["sourcePath"]) != path \
                or path in result or row is None or source["sha256"] != row["sha256"] \
                or source["selector"] != "a:0" or source["selectedStreamIndex"] != row["audioStreamIndex"]:
            raise RuntimeError("source-float channel receipt does not bind the selected source")
        tools = ChannelTools(observed_tools["ffmpegPath"], observed_tools["ffmpegSha256"],
                             observed_tools["ffprobePath"], observed_tools["ffprobeSha256"])
        if any(admission.tools[name] != {"path": observed_tools[name + "Path"],
                                        "sha256": observed_tools[name + "Sha256"]}
               for name in ("ffmpeg", "ffprobe")):
            raise RuntimeError("source-float channel executable differs from admitted tool")
        info = os.stat(path, follow_symlinks=False)
        request = ChannelRequest(path, row["sha256"], "a:0", tools)
        identity = SourceIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        result[path] = ChannelAuthority(request, identity, receipt)
    return result


def seal_audio_record(path: str, body: dict) -> dict:
    """Retain a new exact JSON fact; this is not an approval or cache admission."""
    record = {**body, "receiptHash": content_hash(body)}
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(canonical_compact_json(record))
        handle.flush()
        os.fsync(handle.fileno())
    return record
