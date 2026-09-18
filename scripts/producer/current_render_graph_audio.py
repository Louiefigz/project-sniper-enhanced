"""Explicit source-float audio policy at the existing current-render graph gate."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from audio.assemble_source_audio import PROGRAM_AUDIO_POINTER
from audio.assemble_picture_reuse import picture_reuse_input_hash
from audio.assemble_publication import require_settled
from audio.program_master_cache import load_program_master
from audio.render_audio_cache import SOURCE_BUS_POINTER, load_source_bus, _inside, _hash
from audio.render_audio_bus import SourceAudioBus
from current_render_graph_inputs import GraphBuildInputs
from current_render_graph_contract import object_hash
from cut_preview_io import bound_json, file_hash, digest
from current_render_graph_store import load_active, read_pending_base

_POINTER_KEYS = {"schemaVersion", "kind", "audioClockPolicy", "finalSha256",
    "programMasterReceiptPath", "programMasterReceiptHash", "audioProgramInputHash",
    "pictureReuseInputHash", "pictureSupportSha256"}


def validate_audio_command(policy: str, command: tuple[str, ...]) -> None:
    """A wrapper policy must match its real child before considering a cache hit."""
    values = []
    for index, token in enumerate(command):
        if token == "--audio-clock-policy":
            values.append(command[index + 1] if index + 1 < len(command) else None)
        elif token.startswith("--audio-clock-policy="):
            values.append(token.partition("=")[2])
    if len(values) > 1 or (values[0] if values else "legacy-v1") != policy:
        raise RuntimeError("render graph audio policy differs from its actual renderer command")
    if any(value.startswith("--source-bus-receipt-hash") for value in command):
        raise RuntimeError("source-float child source authority is owned by the graph")


def held_source_bus_hash(inputs: GraphBuildInputs) -> str:
    """Select raw dialogue from durable base handoff or the prior graph only."""
    pending = read_pending_base(inputs.producer_dir)
    if pending is not None:
        if pending.get("schemaVersion") != 2 or pending.get("audioClockPolicy") != "source-float-v2" \
                or pending.get("outputSha256") != file_hash(inputs.base_path):
            raise RuntimeError("source-float pending execution does not bind this base")
        return _hash(pending.get("sourceAudioBusReceiptHash"))
    previous = load_active(inputs.producer_dir)
    if previous is None:
        raise RuntimeError("source-float has no held base execution or prior dialogue graph")
    nodes = {row["nodeId"]: row for row in previous[0]["nodes"]}
    artifacts = {row["nodeId"]: row for row in previous[1]["artifacts"]}
    if "node-dialogue" not in nodes or artifacts["node-base"]["path"] != str(inputs.base_path) \
            or nodes["node-base"]["outputArtifactHash"] != file_hash(inputs.base_path):
        raise RuntimeError("source-float prior dialogue graph does not bind this base")
    return _hash(nodes["node-dialogue"]["inputDigests"].get("audio.sourceReceipt"))


def _source_bus(inputs: GraphBuildInputs, plan: dict, held: str | None = None) -> SourceAudioBus:
    """Reopen current source/cut/channel/float authority from the actual base root."""
    manifest = bound_json(inputs.manifest_path)
    manifest["_path"] = str(inputs.manifest_path)
    expected = held_source_bus_hash(inputs) if held is None else held
    return load_source_bus(plan, manifest, (str(inputs.artifact_root), str(inputs.base_path)), expected)


def _completed_source_hash(inputs: GraphBuildInputs, rendered: Path, events: list[dict]) -> str:
    """Captured child completion binds its actual newly rendered bus receipt."""
    completed = [row["master"] for row in events if row.get("status") == "done" and type(row.get("master")) is dict]
    if len(completed) != 1 or type(completed[0]) is not dict:
        raise RuntimeError("source-float base omitted one exact execution completion")
    master = completed[0]
    path = _inside(master.get("source_audio_receipt"), inputs.artifact_root)
    receipt = bound_json(path)
    if receipt.get("receiptHash") != master.get("source_audio_receipt_hash") \
            or digest({key: value for key, value in receipt.items() if key != "receiptHash"}) != receipt.get("receiptHash") \
            or receipt.get("kind") != "ordinary-source-float-master" or receipt.get("schemaVersion") != 2 \
            or receipt.get("audioClockPolicy") != "source-float-v2" \
            or receipt.get("path") != str(rendered) or receipt.get("sha256") != file_hash(rendered):
        raise RuntimeError("source-float base receipt differs from held renderer completion")
    return _hash(receipt.get("busReceiptHash"))


def audio_pending_facts(inputs: GraphBuildInputs, rendered: Path, plan: dict,
                        events: list[dict] | None = None) -> dict:
    """A v2 pending handoff includes the exact bus pointer, never only base media."""
    if inputs.audio_clock_policy == "legacy-v1":
        return {}
    held = _completed_source_hash(inputs, rendered, events) if events is not None else held_source_bus_hash(inputs)
    bus = _source_bus(replace(inputs, base_path=rendered), plan, held)
    return {"audioClockPolicy": inputs.audio_clock_policy,
        "sourceAudioBusPointerSha256": file_hash(inputs.artifact_root / SOURCE_BUS_POINTER),
        "sourceAudioBusReceiptHash": bus.receipt["receiptHash"]}


def _held_program_hash(events: list[dict], previous: tuple | None) -> str | None:
    """New execution stdout or a prior graph binds selection; mutable JSON does not."""
    completed = [row.get("programAudio") for row in events if row.get("status") == "done"
                 and type(row.get("programAudio")) is dict]
    if completed:
        if len(completed) != 1:
            raise RuntimeError("render graph observed multiple program-audio completions")
        return completed[0].get("programMasterReceiptHash")
    if previous:
        final = next(row for row in previous[0]["nodes"] if row["nodeId"] == "node-final")
        return final["inputDigests"].get("audio.programReceipt")
    return None


def audio_graph_facts(inputs: GraphBuildInputs, plan: dict, authority: tuple) -> dict | None:
    """Bind retained raw dialogue and full master dependencies without approval."""
    if inputs.audio_clock_policy == "legacy-v1":
        return None
    require_settled(inputs.artifact_root)
    events, previous = authority
    bus = _source_bus(inputs, plan)
    pointer = bound_json(inputs.artifact_root / PROGRAM_AUDIO_POINTER)
    held = _held_program_hash(events, previous)
    if set(pointer) != _POINTER_KEYS or pointer["schemaVersion"] != 2 \
            or pointer["kind"] != "ordinary-program-audio-pointer" \
            or pointer["audioClockPolicy"] != inputs.audio_clock_policy \
            or held is None or pointer["programMasterReceiptHash"] != held:
        raise RuntimeError("render graph lacks held full-program execution authority")
    master = load_program_master(bus, plan, (pointer["programMasterReceiptPath"], held))
    visual_key = picture_reuse_input_hash(SimpleNamespace(base=str(inputs.base_path), plan=plan), bus)
    if file_hash(inputs.output_path) != pointer["finalSha256"] \
            or pointer["audioProgramInputHash"] != master.receipt["audioProgramInputHash"] \
            or pointer["pictureReuseInputHash"] != visual_key:
        raise RuntimeError("render graph final or full-program audio inputs changed")
    return {"artifact": {"nodeId": "node-dialogue", "path": bus.path,
        "sha256": bus.sha256, "sizeBytes": Path(bus.path).stat().st_size},
        "sourceInputs": {"audio.sourceReceipt": bus.receipt["receiptHash"],
            "audio.input": bus.admission.audio_input_hash, "audio.policy": object_hash(inputs.audio_clock_policy)},
        "finalInputs": {"audio.programReceipt": held,
            "picture.reuse": visual_key,
            "audio.programInput": master.receipt["audioProgramInputHash"],
            "audio.masterPcm": master.receipt["masteredAudio"]["sha256"],
            "audio.policy": object_hash(inputs.audio_clock_policy)}}
