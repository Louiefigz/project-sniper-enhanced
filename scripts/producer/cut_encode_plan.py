"""Cut encoder geometry, seam inputs and typed command-planning values."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

from audio.channel_normalization import ChannelAuthority
from audio.cut_audio_filters import CutAudioFilter, fade_suffix, source_filter
from compile_timeline import Segment
from cut_reframe import FusedReframe
from producer_config import ENCODE

if TYPE_CHECKING:
    from guided_source_color_consumption import SourceColorPictureConsumption

AUDIO_RATE = ENCODE["audio_rate"]

@dataclass(frozen=True)
class Profile:
    """Common target every segment is normalized to (from the first source)."""

    width: int
    height: int
    fps: Fraction
    pix_fmt: str

    @property
    def fps_arg(self) -> str:
        """ffmpeg rational fps string, e.g. ``30000/1001``."""
        return f"{self.fps.numerator}/{self.fps.denominator}"

    @property
    def frame_s(self) -> float:
        """Duration of one frame in seconds."""
        return 1.0 / float(self.fps)

    @property
    def video_timescale(self) -> int:
        """MP4 track timescale that carries this frame rate exactly (kept
        >= 10000 like ffmpeg's own default, so a frame is a whole tick count)."""
        scale = self.fps.numerator
        while scale < 10000:
            scale *= 10
        return scale

    @property
    def frame_ticks(self) -> int:
        """Exact duration of one frame in ``video_timescale`` ticks."""
        return self.video_timescale // self.fps.numerator * self.fps.denominator

    def audio_samples(self, frames: int) -> int:
        """Nearest whole 48 kHz sample count for exactly ``frames`` frames."""
        return round(Fraction(frames * AUDIO_RATE) / self.fps)



def proxy_profile(profile: Profile, scale: float) -> Profile:
    """The DOWNSCALED proxy variant of a profile (geometry contract v3 A1).

    Only the canvas shrinks (even-snapped); fps and pix_fmt are untouched, so
    every downstream trim/setpts/atempo/fps term — the segment math — runs
    bit-identically to the full render, just onto smaller frames.

    Args:
        profile: The full-resolution common profile.
        scale: Downscale factor in (0, 1].

    Returns:
        The proxy Profile.

    Raises:
        ValueError: On a scale outside (0, 1].
    """
    if not 0.0 < scale <= 1.0:
        raise ValueError(f"proxy scale {scale} outside (0, 1]")
    width = max(2, int(round(profile.width * scale / 2.0)) * 2)
    height = max(2, int(round(profile.height * scale / 2.0)) * 2)
    return Profile(width=width, height=height, fps=profile.fps,
                   pix_fmt=profile.pix_fmt)



def _video_chain(seg: Segment, pre_seek: float, profile: Profile,
                 reframe: FusedReframe | None = None) -> str:
    """Trim the exact source window, apply speed, scale + letterbox to profile,
    then force CFR at the profile fps."""
    fs, fe = seg.src_start - pre_seek, seg.src_end - pre_seek
    if reframe is not None:
        return (f"[0:v]trim=start={fs:.6f}:end={fe:.6f},"
                f"setpts=(PTS-STARTPTS)/{seg.speed},{reframe.video_filter},"
                f"fps=fps={profile.fps_arg}[v]")
    pw, ph = profile.width, profile.height
    return (
        f"[0:v]trim=start={fs:.6f}:end={fe:.6f},"
        f"setpts=(PTS-STARTPTS)/{seg.speed},"
        f"scale={pw}:{ph}:force_original_aspect_ratio=decrease:eval=init,"
        f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"fps=fps={profile.fps_arg}[v]"
    )



def _fade_suffix(out_len: float, fade_s: float) -> str:
    """15 ms equal-power (qsin) fade in+out at each part's edges — declicks the
    concat joins without acrossfade's N-part duration drift (PRODUCER_PLAN §4.2;
    the lead-specified Phase-1 join treatment). Clamped for very short parts."""
    return fade_suffix(out_len, fade_s)



def _audio_chain(
    seg: Segment,
    pre_seek: float,
    out_len: float,
    authority: ChannelAuthority | bool | None,
) -> str:
    """Trim + atempo the source audio (or synthesize silence), normalize to
    48 kHz stereo, and taper both edges to declick the join.

    ``out_len`` is the OWN audio length this part contributes — the full
    video length, minus a J-cut tail when the next segment's lead audio is
    appended after it (``encode_segment``'s [tail] chain). Labeled [own];
    the caller maps it (or concats the tail) to the final [a].
    """
    return source_filter(CutAudioFilter(
        seg.src_start - pre_seek, out_len, seg.speed, authority,
        source_end=seg.src_start + out_len * seg.speed - pre_seek), "own")



@dataclass(frozen=True)
class TailLead:
    """The J-cut tail of one part: the NEXT segment's audio pre-roll.

    ``lead_s`` OUTPUT seconds of the next segment's source audio, ending at
    its in-point (``src_start``), retimed by its ``speed``. ``src_path`` may
    differ from the part's own source (multi-source cuts).
    """

    lead_s: float
    src_path: str
    src_start: float
    speed: float



@dataclass(frozen=True)
class EncodeJob:
    """Everything one part's encode needs beyond its Segment."""

    src_path: str
    profile: Profile
    tail: TailLead | None = None
    source_channels: ChannelAuthority | None = None
    tail_channels: ChannelAuthority | None = None
    before_encode: Callable[[], None] | None = None  # Internal original owner; never a CLI/JSON option.
    picture_consumption: SourceColorPictureConsumption | None = None
    reframe: FusedReframe | None = None



def _tail_chain(
    tail: TailLead,
    idx: int,
    authority: ChannelAuthority | bool | None,
) -> str:
    """The J-cut lead piece: pre-in-point source audio → ``lead_s`` output
    seconds, normalized + 15 ms edge-declicked (the seam's audio switch gets
    the SAME join treatment every part boundary gets), labeled [tail]."""
    return source_filter(CutAudioFilter(
        tail.src_start - tail.lead_s * tail.speed, tail.lead_s,
        tail.speed, authority, idx, idx, source_end=tail.src_start), "tail")



def _tail_inputs(tail: TailLead, has_tail_audio: bool) -> list[str]:
    """The extra ffmpeg input for a part's J-cut tail → (args, has_audio)."""
    if not has_tail_audio:
        return ["-f", "lavfi", "-t", f"{tail.lead_s + 0.5:.3f}",
                "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
    seek = _tail_seek(tail)
    return ((["-ss", f"{seek:.6f}"] if seek > 0 else [])
            + ["-i", tail.src_path])



def _tail_seek(tail: TailLead) -> float:
    """The input-side seek applied by :func:`_tail_inputs` (0 when none)."""
    return max(0.0, tail.src_start - tail.lead_s * tail.speed - 1.0)


@dataclass(frozen=True)
class CutSpeedOptions:
    """Optional knobs for one cut+speed render (keeps entry points ≤4 params).

    Attributes:
        work_dir: Where the per-segment parts land.
        proxy_scale: When set, render a DOWNSCALED proxy mezzanine through the
            SAME segment math (see :func:`proxy_profile`); ``None`` = full res.
    """

    work_dir: str
    proxy_scale: float | None = None
    before_encode: Callable[[], None] | None = None
    picture_consumption: SourceColorPictureConsumption | None = None
    reframe: FusedReframe | None = None
