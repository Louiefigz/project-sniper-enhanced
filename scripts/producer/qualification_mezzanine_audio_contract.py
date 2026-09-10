"""Full-program mastered-audio checks for qualification mezzanines."""
from __future__ import annotations


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise RuntimeError(f"qualification {label} is not numeric")
    number = float(value)
    if not number >= 0 or number == float("inf"):
        raise RuntimeError(f"qualification {label} is invalid")
    return number


def _expected_samples(target_frames: int, target_fps: int) -> int:
    numerator = target_frames * 48000
    if numerator % target_fps:
        raise RuntimeError("qualification target has a fractional audio sample")
    return numerator // target_fps


def _timeline_samples(program_samples: int) -> int:
    quantum = 48
    return ((program_samples + quantum - 1) // quantum) * quantum


def _audio_context(target_frames: int, target_fps: int) -> dict:
    program = _expected_samples(target_frames, target_fps)
    timeline = _timeline_samples(program)
    return {
        "program": program,
        "timeline": timeline,
        "silent_tail": timeline - program,
        "program_duration": program / 48000,
        "timeline_duration": timeline / 48000,
        "filter": (
            "aresample=48000:async=0:first_pts=0,"
            f"atrim=end_sample={program},apad=whole_len={timeline},"
            f"atrim=end_sample={timeline},asetpts=N/SR/TB"
        ),
    }


def _decision_matches(decision: dict, context: dict) -> bool:
    return (
        decision.get("mode") == "full-program-with-bounded-silent-aac-tail"
        and decision.get("sampleRate") == 48000
        and decision.get("channels") == 2
        and decision.get("programSamplesPerChannel") == context["program"]
        and decision.get("targetTimelineSamplesPerChannel") == context["timeline"]
        and decision.get("presentationQuantumSamples") == 48
        and decision.get("silentTailSamplesPerChannel") == context["silent_tail"]
        and 0 <= context["silent_tail"] < 48
        and abs(_number(decision.get("programDurationSeconds"),
                        "audio program duration") - context["program_duration"]) < 1e-9
        and abs(_number(decision.get("targetTimelineDurationSeconds"),
                        "audio target duration") - context["timeline_duration"]) < 1e-9
        and decision.get("filter") == context["filter"]
    )


def _facts_match(audio: dict, context: dict) -> bool:
    decoded = audio.get("decodedSamplesPerChannel")
    padding = audio.get("codecPaddingSamplesPerChannel")
    valid_integers = (
        type(decoded) is int and not isinstance(decoded, bool)
        and type(padding) is int and not isinstance(padding, bool)
    )
    return (
        audio.get("codec") == "aac"
        and audio.get("sampleRate") == 48000
        and audio.get("channels") == 2
        and audio.get("timeBase") == "1/48000"
        and audio.get("startPts") == 0
        and audio.get("programSamplesPerChannel") == context["program"]
        and audio.get("timelineSamplesPerChannel") == context["timeline"]
        and abs(_number(audio.get("timelineDurationSeconds"),
                        "audio timeline duration") - context["timeline_duration"])
        <= 0.0000005
        and audio.get("silentTailSamplesPerChannel") == context["silent_tail"]
        and valid_integers and decoded >= context["timeline"]
        and padding == decoded - context["timeline"] and 0 <= padding < 1024
        and abs(_number(audio.get("decodedDurationSeconds"),
                        "audio decoded duration") - decoded / 48000) < 1e-9
        and audio.get("fullProgramCoverage") is True
    )


def validate_audio(
    worker: dict,
    target_frames: int,
    target_fps: int,
) -> None:
    """Require full program coverage plus a bounded silent AAC/MP4 tail."""
    decision = worker.get("audioDecision")
    facts = (worker.get("outputProbe") or {}).get("facts") or {}
    audio = facts.get("audio")
    if type(decision) is not dict or type(audio) is not dict:
        raise RuntimeError("qualification audio authority is missing")
    context = _audio_context(target_frames, target_fps)
    if not _decision_matches(decision, context) \
            or not _facts_match(audio, context):
        raise RuntimeError("qualification full-program AAC audio is inconsistent")
