"""Exact color-transform validation for qualification mezzanines."""
from __future__ import annotations


def _color_filter(mode: str, target_rate: str, target_frames: int) -> str:
    geometry = (
        "scale=1920:1080:force_original_aspect_ratio=decrease:"
        "flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps=fps={target_rate}:start_time=0:round=near,"
        f"trim=end_frame={target_frames},setpts=PTS-STARTPTS,format=yuv420p"
    )
    prefixes = {
        "retain-bt709-sdr": "",
        "normalize-xvycc-bt709-to-bt709-sdr": (
            "zscale=t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709:t=bt709:m=bt709:r=tv,"
        ),
        "tone-map-hdr-to-bt709-sdr": (
            "zscale=t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,"
        ),
    }
    return prefixes[mode] + geometry


def _color_mode(source: dict) -> tuple[bool, str]:
    hdr = (
        source.get("transfer") in {"smpte2084", "arib-std-b67"}
        or source.get("primaries") == "bt2020"
    )
    if hdr:
        return True, "tone-map-hdr-to-bt709-sdr"
    xvycc = (
        source.get("space") == "bt709"
        and source.get("transfer") == "iec61966-2-4"
        and source.get("primaries") == "bt709"
    )
    if xvycc:
        return False, "normalize-xvycc-bt709-to-bt709-sdr"
    if all(source.get(key) == "bt709"
           for key in ("space", "transfer", "primaries")):
        return False, "retain-bt709-sdr"
    raise RuntimeError("qualification color decision is inconsistent")


def validate_color(worker: dict) -> None:
    """Require the exact transform implied by the declared source tags."""
    color = worker.get("colorDecision")
    if type(color) is not dict:
        raise RuntimeError("qualification color decision is missing")
    source, target = color.get("sourceTags"), color.get("targetTags")
    expected = {"range": "tv", "space": "bt709", "transfer": "bt709",
                "primaries": "bt709", "pixelFormat": "yuv420p"}
    exact_source = (
        type(source) is dict
        and set(source) == {"range", "space", "transfer", "primaries",
                            "pixelFormat"}
        and source.get("range") == "tv"
    )
    if not exact_source:
        raise RuntimeError("qualification color decision is inconsistent")
    hdr, mode = _color_mode(source)
    cadence = worker.get("cadenceDecision") or {}
    target_rate, target_frames = cadence.get("targetRate"), \
        cadence.get("targetFrames")
    if (color.get("hdrDetected") is not hdr
            or color.get("mode") != mode or target != expected
            or type(target_rate) is not str
            or type(target_frames) is not int
            or color.get("filter") != _color_filter(
                mode, target_rate, target_frames)):
        raise RuntimeError("qualification color decision is inconsistent")
