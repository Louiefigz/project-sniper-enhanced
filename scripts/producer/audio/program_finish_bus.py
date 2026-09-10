"""Apply validated finishing to the retained float bus, sample-exact and unmastered.

Order: cleanup then gain on the dialogue signal; authored SFX are summed after
cleanup so voice filters never process them; music ducking (program_mix_bus)
is keyed by the finished dialogue without SFX; the single whole-program master
follows. Every intermediate stays pcm_f32le at the exact bus clock. Cleanup
filters are not latency-free (afftdn 1200 samples, arnndn 480 on FFmpeg 8) and
do not flush that delayed tail at end of input, so the delay of the exact
installed chain is measured with an impulse, the chain input is padded by that
many samples plus a guard (so block-based filters never see the end of input
inside the program range), and the delay is then removed: every program sample,
including the final ones, is the processed source sample. Nothing here approves
audio or delivers media.
"""
from __future__ import annotations

import array
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audio.audio_gain import RAMP_S
from audio.audio_gain import build_filter as gain_filter
from audio.audio_mix_bed import AFMT
from audio.program_audio_clock import float_audio_clock
from audio.program_finish_contract import (FINISHING_POLICY_VERSION, FinishRequest, SfxCue,
    finishing_request, finishing_settings, requested_settings, sfx_key)
from audio.render_audio_authority import run_audio
from audio.render_audio_bus import SourceAudioBus
from cut_preview_io import file_hash

PROBE_SECONDS = 2
IMPULSE_SAMPLE = 48_000         # the probe click sits one second in
MAX_LATENCY_SAMPLES = 48_000    # a chain delaying more than one second is not cleanup
MIN_PROBE_PEAK = 0.05           # the click must survive the chain to be located
ENVELOPE_FRAME = 256            # gain envelope evaluation cadence (5.3 ms)
TAIL_GUARD_SAMPLES = 4800       # 100 ms of extra input padding past the measured delay
ORDER = "cleanup->gain->sfx->music->master"
DETECTOR_KEY = "finished-dialogue-without-sfx"
_MODEL_RE = re.compile(r"arnndn=m=([^,:]+)")
_RECORD_KEYS = {"policyVersion", "order", "settings", "detectorKey", "cleanup", "gain", "sfx",
                "dialogue", "program"}


@dataclass(frozen=True)
class FinishedProgram:
    """Finished dialogue (the sidechain key) and the audible pre-music program."""

    dialogue_path: str
    dialogue_sha256: str
    program_path: str
    program_sha256: str
    receipt: dict


def measure_chain_latency(ffmpeg: str, chain: str) -> int:
    """Locate a unit click after the exact chain; reject a lost click or moved clock."""
    total = PROBE_SECONDS * 48_000
    click = f"if(eq(n,{IMPULSE_SAMPLE}),0.9,0)"
    raw = run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-f", "lavfi", "-i",
        f"aevalsrc='{click}|{click}':s=48000:d={PROBE_SECONDS}",
        "-af", f"{chain},{AFMT}", "-c:a", "pcm_f32le", "-f", "f32le", "-"])
    samples = array.array("f")
    samples.frombytes(raw)
    if len(samples) != 2 * total:
        raise RuntimeError("cleanup chain changed the probe sample count; it cannot keep the program clock")
    left = [abs(samples[2 * index]) for index in range(total)]
    peak = max(range(total), key=left.__getitem__)
    lag = peak - IMPULSE_SAMPLE
    if left[peak] < MIN_PROBE_PEAK or not 0 <= lag <= MAX_LATENCY_SAMPLES:
        raise RuntimeError("cleanup chain latency could not be established "
                           f"(peak {left[peak]:.3f} at {lag:+d} samples)")
    return lag


def _dialogue_filter(request: FinishRequest, latency: int, samples: int) -> str:
    """Cleanup, delay removal, then the existing trapezoid gain windows at the bus clock.

    The chain input is padded by the measured delay plus a guard so the filter
    also emits the processed final ``latency`` samples instead of leaving that
    tail silent, and no end-of-input block handling touches the program range."""
    parts = []
    if request.enhance_chain:
        parts.append(f"apad=pad_len={latency + TAIL_GUARD_SAMPLES}")
        parts.append(request.enhance_chain)
        parts.append(f"atrim=start_sample={latency},asetpts=N/SR/TB")
    parts.append(AFMT)
    if request.gain:
        parts.append(f"asetnsamples=n={ENVELOPE_FRAME}:p=0,{gain_filter(list(request.gain))}")
    parts.append(f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB")
    return ",".join(parts)


def _render_dialogue(bus: SourceAudioBus, request: FinishRequest, directory: Path) -> tuple[str, int]:
    """Finished dialogue stem with the measured cleanup delay removed."""
    ffmpeg = bus.admission.tools["ffmpeg"]["path"]
    latency = measure_chain_latency(ffmpeg, request.enhance_chain) if request.enhance_chain else 0
    target = directory / "dialogue-finished.wav"
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-n",
        "-i", bus.path, "-map", "0:a:0", "-af", _dialogue_filter(request, latency, bus.samples),
        "-ac", "2", "-c:a", "pcm_f32le", str(target)])
    float_audio_clock(str(target), bus)
    return str(target), latency


def _sfx_sources(request: FinishRequest, directory: Path) -> dict[str, dict]:
    """Synthesize the engine whoosh once and bind every consumed one-shot's bytes."""
    sources: dict[str, dict] = {}
    for cue in request.sfx:
        key = sfx_key(cue)
        if key in sources:
            continue
        path = cue.path
        if path is None:
            from motion.transitions import synth_whoosh
            path = str(directory / "engine-whoosh.wav")
            synth_whoosh(path)
        sources[key] = {"path": path, "sha256": file_hash(Path(path)), "leadS": cue.lead_s}
    return sources


def cue_start_sample(cue: SfxCue) -> int:
    """The hit lands on the seam: playback starts ``lead`` before it, never before zero."""
    return max(0, round((cue.out_time - cue.lead_s) * 48_000))


def _sfx_graph(request: FinishRequest, sources: dict[str, dict], samples: int) -> tuple[list[str], str]:
    """Delay each cue sample-exactly onto its seam and sum at unity, pinned to the program."""
    inputs: list[str] = []
    parts, delayed = [f"[0:a]{AFMT}[program]"], []
    for index, key in enumerate(sources, start=1):
        inputs += ["-i", sources[key]["path"]]
        cues = [cue for cue in request.sfx if sfx_key(cue) == key]
        taps = [f"[i{index}]"] if len(cues) == 1 else [f"[i{index}s{n}]" for n in range(len(cues))]
        split = f",asplit={len(cues)}" if len(cues) > 1 else ""
        parts.append(f"[{index}:a]{AFMT}{split}" + "".join(taps))
        for tap, cue in zip(taps, cues):
            start, label = cue_start_sample(cue), f"[d{len(delayed)}]"
            parts.append(f"{tap}adelay={start}S|{start}S{label}")
            delayed.append(label)
    parts.append("[program]" + "".join(delayed) + f"amix=inputs={len(delayed) + 1}:duration=first:"
                 f"normalize=0,{AFMT},atrim=end_sample={samples},asetpts=N/SR/TB[out]")
    return inputs, ";".join(parts)


def _render_program(bus: SourceAudioBus, context: tuple, directory: Path) -> str:
    """Finished dialogue plus every seam sound; float sum, no master, exact clock."""
    request, dialogue, sources = context
    inputs, graph = _sfx_graph(request, sources, bus.samples)
    target = directory / "program-finished.wav"
    run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-xerror",
        "-err_detect", "explode", "-n", "-i", dialogue, *inputs, "-filter_complex", graph,
        "-map", "[out]", "-c:a", "pcm_f32le", str(target)])
    float_audio_clock(str(target), bus)
    return str(target)


def _model_binding(chain: str | None) -> dict | None:
    """Bind the vendored RNNoise model bytes when the chain consumes one."""
    match = _MODEL_RE.search(chain or "")
    if match is None:
        return None
    path = Path(match.group(1))
    return {"path": str(path), "sha256": file_hash(path)}


def _receipt(request: FinishRequest, context: tuple, media: tuple[str, str]) -> dict:
    """Retain settings, consumed assets, measured delay and exact output identities."""
    latency, model, sources = context
    dialogue, program = media
    return {"policyVersion": FINISHING_POLICY_VERSION, "order": ORDER,
        "settings": finishing_settings(request), "detectorKey": DETECTOR_KEY,
        "cleanup": None if not request.enhance_chain else {"preset": request.enhance_preset,
            "filter": request.enhance_chain, "measuredLatencySamples": latency,
            "inputPaddingSamples": latency + TAIL_GUARD_SAMPLES, "model": model},
        "gain": None if not request.gain else {"filter": gain_filter(list(request.gain)),
            "rampS": RAMP_S, "envelopeFrameSamples": ENVELOPE_FRAME},
        "sfx": None if not request.sfx else {"cues": [{"outTime": cue.out_time, "sfx": cue.sfx,
            "leadS": cue.lead_s, "startSample": cue_start_sample(cue), "source": sfx_key(cue)}
            for cue in request.sfx], "sources": sources},
        "dialogue": {"path": dialogue, "sha256": file_hash(Path(dialogue))},
        "program": {"path": program, "sha256": file_hash(Path(program))}}


def render_finishing(bus: SourceAudioBus, plan: dict, directory: Path) -> FinishedProgram | None:
    """Execute the plan's finishing on this bus; None when the plan requests none."""
    request = finishing_request(plan, bus.samples / 48_000)
    if request is None:
        return None
    model = _model_binding(request.enhance_chain)
    sources = _sfx_sources(request, directory)
    dialogue, latency = ((bus.path, 0) if not (request.enhance_chain or request.gain)
                         else _render_dialogue(bus, request, directory))
    program = _render_program(bus, (request, dialogue, sources), directory) if request.sfx else dialogue
    receipt = _receipt(request, (latency, model, sources), (dialogue, program))
    assert_finishing_stable(receipt)
    return FinishedProgram(dialogue, receipt["dialogue"]["sha256"], program,
                           receipt["program"]["sha256"], receipt)


def finishing_identity(record: dict | None) -> dict | None:
    """Path-free identity of everything that shaped the finished program."""
    if record is None:
        return None
    cleanup, sfx = record["cleanup"], record["sfx"]
    return {"policyVersion": record["policyVersion"], "order": record["order"],
        "settings": record["settings"], "detectorKey": record["detectorKey"],
        "cleanup": None if cleanup is None else {**{key: value for key, value in cleanup.items() if key != "model"},
            "modelSha256": None if cleanup["model"] is None else cleanup["model"]["sha256"]},
        "gain": record["gain"],
        "sfx": None if sfx is None else {"cues": sfx["cues"], "sources": {
            key: {"sha256": value["sha256"], "leadS": value["leadS"]} for key, value in sfx["sources"].items()}},
        "dialogueSha256": record["dialogue"]["sha256"], "programSha256": record["program"]["sha256"]}


def _consumed(record: dict) -> list[tuple[str, dict]]:
    """Every external byte source the finished program depends on."""
    rows = [("cleanup model", record["cleanup"]["model"])] if record["cleanup"] and record["cleanup"]["model"] else []
    rows += [(f"SFX source {key}", value) for key, value in ((record["sfx"] or {}).get("sources") or {}).items()]
    return rows


def assert_finishing_stable(record: dict | None) -> None:
    """Consumed model/SFX bytes and both finished stems must still be the bound bytes."""
    if record is None:
        return
    for label, item in _consumed(record) + [("finished dialogue", record["dialogue"]), ("finished program", record["program"])]:
        if file_hash(Path(item["path"])) != item["sha256"]:
            raise RuntimeError(f"full-program master {label} bytes changed")


def verify_finishing(record: dict | None, bus: SourceAudioBus, plan: dict) -> None:
    """The plan's current request must equal the retained settings, assets unchanged."""
    expected = requested_settings(plan, bus.samples / 48_000)
    if expected != (None if record is None else record["settings"]):
        raise RuntimeError("full-program master finishing settings changed")
    assert_finishing_stable(record)


def validate_finishing_record(record: object, bus: SourceAudioBus, bound: Callable[[dict], Path]) -> None:
    """Exact role/version fields and retained stems inside the bus generation."""
    if type(record) is not dict or set(record) != _RECORD_KEYS \
            or record["policyVersion"] != FINISHING_POLICY_VERSION or record["order"] != ORDER \
            or record["detectorKey"] != DETECTOR_KEY or type(record["settings"]) is not dict:
        raise RuntimeError("program finishing record is malformed or stale")
    for item in (record["dialogue"], record["program"]):
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise RuntimeError("program finishing stem identity is malformed")
        bound(item)
    for label, item in _consumed(record):
        _validate_consumed(label, item, Path(bus.directory), bound)


def _validate_consumed(label: str, item: object, root: Path, bound: Callable[[dict], Path]) -> None:
    """Retained stems bind inside the generation; pack assets and the model re-hash in place."""
    if type(item) is not dict or type(item.get("path")) is not str:
        raise RuntimeError(f"program finishing {label} identity is malformed")
    if Path(item["path"]).is_relative_to(root):
        bound(item)
        return
    if file_hash(Path(item["path"])) != item["sha256"]:
        raise RuntimeError(f"program finishing {label} bytes changed")
