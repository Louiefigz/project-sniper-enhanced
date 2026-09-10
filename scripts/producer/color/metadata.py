"""Conservative named input-class screening; never guess a Log/HDR transform."""
from __future__ import annotations

_FIELDS = {"color_range": "range", "color_space": "matrix",
           "color_transfer": "transfer", "color_primaries": "primaries",
           "pix_fmt": "pixelFormat", "bits_per_raw_sample": "bitsPerRawSample",
           "codec_name": "codec", "start_time": "startTime",
           "avg_frame_rate": "frameRate"}


def source_metadata(probe: dict) -> dict:
    """Preserve probed color/HDR facts, including missing and conflicting tags."""
    streams = probe.get("streams") or []
    if type(streams) is not list or any(type(row) is not dict for row in streams):
        raise ValueError("color probe stream metadata is malformed")
    video = [row for row in streams if row.get("codec_type") == "video"]
    if len(video) != 1:
        raise ValueError("color diagnostic requires exactly one video stream")
    stream = video[0]
    facts = {label: stream.get(key) for key, label in _FIELDS.items()}
    facts.update(width=stream.get("width"), height=stream.get("height"),
                 duration=stream.get("duration", (probe.get("format") or {}).get("duration")),
                 sideData=stream.get("side_data_list") or [],
                 tags=stream.get("tags") or {},
                 formatTags=(probe.get("format") or {}).get("tags") or {})
    hdr = facts["transfer"] in {"smpte2084", "arib-std-b67"}
    hdr_side = any(any(token in str(row.get("side_data_type", "")).lower()
                          for token in ("mastering", "content light", "dovi", "hdr"))
                   for row in facts["sideData"])
    positive = (facts["range"] == "tv" and facts["matrix"] == "bt709"
                and facts["transfer"] == "bt709" and facts["primaries"] == "bt709"
                and facts["pixelFormat"] == "yuv420p"
                and facts["bitsPerRawSample"] in (None, "0", "8", 0, 8)
                and not hdr_side)
    facts["supportedSamplingClass"] = "limited-8bit-bt709" if positive else None
    facts["hdrSignaled"] = hdr or hdr_side
    facts["logProfileInferred"] = False
    return facts


def context_warnings(facts: dict, declared: dict) -> list[str]:
    """Keep uncertainty intact instead of merging a guessed grade into a plan."""
    warnings = []
    if not facts["supportedSamplingClass"]:
        warnings.append("Input is outside limited-range 8-bit BT.709 sampling; no conversion or grade was guessed.")
    if facts["hdrSignaled"] or declared["sourceProfile"] == "hdr":
        warnings.append("HDR requires an explicitly reviewed input/delivery transform; this diagnostic does not tone-map.")
    if declared["sourceProfile"] in {"unknown", "log"}:
        warnings.append("Source profile is unknown or Log; flat appearance and BT.709 tags cannot identify camera Log.")
    if declared["cameraProfile"]:
        warnings.append("Camera profile is declared but no camera-specific transform is implemented in this private diagnostic.")
    if declared["historyState"] != "known":
        warnings.append("Prior transforms are unknown; do not add a correction or transform until history is reviewed.")
    if declared["transformHistory"]:
        warnings.append("Existing transform history is retained as operator context, not verified transformation evidence.")
    return warnings
