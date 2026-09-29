"""Native project adapter for the shared long-form dialogue cleanup processor."""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from audio.dialogue_cleanup import (DialogueSource, cleanup_model_binding,
                                    render_clean_dialogue)
from audio.program_audio_clock import exact_float_audio_clock
from audio.program_finish_contract import FinishRequest, finishing_request, finishing_settings
from cut_preview_io import file_hash


def native_finishing_request(value: object, samples: int) -> FinishRequest | None:
    """Validate project metadata, then reuse the existing gain/preset parser."""
    if type(samples) is not int or samples <= 0:
        raise ValueError("Native finishing requires a positive integer sample clock")
    if value is None:
        return None
    keys = {"schemaVersion", "rationale", "channelMode", "audioEnhance", "audioGain"}
    if type(value) is not dict or set(value) - keys:
        raise ValueError("Malformed native audio finishing object")
    rationale = value.get("rationale")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1 \
            or type(rationale) is not str or not 3 <= len(rationale.strip()) <= 2400 \
            or len(rationale) > 2400 or "\0" in rationale:
        raise ValueError("Native audio finishing requires a source-specific rationale")
    _validate_fields(value)
    request = _channel_request(finishing_request(value, samples / 48000), value, samples)
    if request is None:
        raise ValueError("Native audio finishing has no processing decision")
    if any(window.out_end > samples / 48000 for window in request.gain):
        raise ValueError("Native gain window exceeds the exact output duration")
    if list(request.gain) != sorted(request.gain, key=lambda window: window.out_start):
        raise ValueError("Native gain windows must be ordered")
    return request


def _channel_request(request: FinishRequest | None, value: dict,
                     samples: int) -> FinishRequest | None:
    """Process one equal-weight mono bus, then duplicate it without pan-law gain."""
    if value.get("channelMode", "stereo") != "mono":
        return request
    request = request or FinishRequest(samples / 48000, None, None, (), ())
    filters = ["pan=mono|c0=0.5*c0+0.5*c1"]
    if request.enhance_chain:
        filters.append(request.enhance_chain)
    filters.append("pan=stereo|c0=c0|c1=c0")
    return replace(request, enhance_chain=",".join(filters))


def _validate_fields(value: dict) -> None:
    """Keep the native contract closed without duplicating shared gain arithmetic."""
    if "channelMode" in value and value["channelMode"] not in ("mono", "stereo"):
        raise ValueError("Native audio channel mode must be mono or stereo")
    if "audioEnhance" in value:
        enhance = value["audioEnhance"]
        if type(enhance) is not dict or set(enhance) != {"preset"} \
                or enhance["preset"] not in ("voice", "voice-strong", "voice-rnn"):
            raise ValueError("Native audio requires an installed local cleanup preset")
    if "audioGain" not in value:
        return
    rows = value["audioGain"]
    if type(rows) is not list or not 1 <= len(rows) <= 128:
        raise ValueError("Native gain requires 1–128 windows")
    if any(type(row) is not dict or set(row) != {"outStart", "outEnd", "dB"} for row in rows):
        raise ValueError("Native gain requires exact output-time window fields")


def finish_native_audio(source: DialogueSource, value: object, directory: Path) -> Path:
    """Keep raw audio intact and bind requested processing to sample-exact local evidence."""
    request = native_finishing_request(value, source.samples)
    if request is None:
        return Path(source.path)
    directory.mkdir(exist_ok=False)
    model = cleanup_model_binding(request.enhance_chain)
    record = dict(schemaVersion=1, status="incomplete", humanListeningApproved=False,
                  settings=finishing_settings(request), rationale=value["rationale"],
                  channelMode=value.get("channelMode", "stereo"),
                  processingFilter=request.enhance_chain,
                  sourceSha256=file_hash(Path(source.path)), model=model)
    try:
        output, latency = render_clean_dialogue(source, request, directory)
        if cleanup_model_binding(request.enhance_chain) != model:
            raise RuntimeError("Dialogue cleanup model changed during processing")
        record.update(status="processed", output=output, outputSha256=file_hash(Path(output)),
                      removedLatencySamples=latency,
                      outputClock=exact_float_audio_clock(output, source.ffprobe, source.samples))
        return Path(output)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error))
        raise
    finally:
        (directory / "receipt.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
