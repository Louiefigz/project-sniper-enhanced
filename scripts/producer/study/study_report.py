#!/usr/bin/env python3
"""study_report — assemble the STUDY fingerprint.json (machine) + report.md (human).

``fingerprint.json`` is the machine artefact the doctrine loop consumes: every
pacing / state / audio number in one structured blob. ``report.md`` is the human
+ brain-facing companion: a pacing summary, a state timeline strip, the audio
profile, and — the point of the whole exercise — a VISION REVIEW CHECKLIST that
walks the brain state-by-state through what to classify from each representative
JPG (layout archetype / graphics present / caption style / text proportion),
exactly like the Audit B checklist but aimed at *learning* a reference's style
rather than QC-ing an output.
"""

from __future__ import annotations

from dataclasses import asdict

from study.study_audio import AudioProfile
from study.study_cuts import PacingStats
from study.study_states import StudyState


def build_fingerprint(meta: dict, pacing: PacingStats, states: list[StudyState],
                      audio: AudioProfile, transcript: dict | None) -> dict:
    """The complete machine-readable fingerprint for one reference video."""
    return {
        "video": meta.get("video"),
        "generatedAt": meta.get("generatedAt"),
        "params": {"fps": meta.get("fps"), "dedupThreshold": meta.get("threshold"),
                   "scdetThreshold": meta.get("scdetThreshold")},
        "pacing": asdict(pacing),
        "states": [asdict(s) for s in states],
        "audio": asdict(audio),
        "transcript": transcript,
    }


def _pacing_table(p: PacingStats) -> list[str]:
    """Pacing summary + shot-length percentiles as markdown."""
    return [
        "## Pacing", "",
        "| Metric | Value |", "|---|---|",
        f"| Duration | {p.duration:.1f}s |",
        f"| Cuts | {p.cut_count} |",
        f"| Cuts / min | {p.cuts_per_min} |",
        f"| Shots | {p.shot_count} |",
        f"| Shot length p25/p50/p75/p95 | {p.shot_p25} / {p.shot_p50} / "
        f"{p.shot_p75} / {p.shot_p95} s |",
        f"| Longest static stretch | {p.longest_static_s:.2f}s |", "",
        "### Cuts-per-10s curve", "",
        "| Window | Cuts | Cuts/min |", "|---|---|---|",
        *[f"| {b['start']:.0f}–{b['end']:.0f}s | {b['cuts']} | "
          f"{b['cutsPerMin']} |" for b in p.bucket_curve], "",
    ]


def _timeline_strip(states: list[StudyState]) -> list[str]:
    """One row per distinct on-screen state with its deterministic signals."""
    lines = [
        "## State timeline", "",
        f"{len(states)} distinct on-screen state(s). "
        "`busy` = screen-content spread (0-1); `face%` = face box / frame.", "",
        "| # | t start | dur | face | face% | busy | luma | colors | rep |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in states:
        face = "prominent" if s.face_prominent else "yes" if s.face_present else "—"
        luma = f"{s.mean_luma:.0f}" if s.mean_luma is not None else "?"
        colors = " ".join(s.dominant_colors[:3]) or "—"
        rep = s.rep_path.split("/states/")[-1]
        lines.append(
            f"| {s.index} | {s.t_start:.1f}s | {s.duration:.1f}s | {face} | "
            f"{s.face_area_frac:.2f} | {s.busy_frac:.2f} | {luma} | {colors} | "
            f"`{rep}` |")
    lines.append("")
    return lines


def _audio_section(a: AudioProfile) -> list[str]:
    """Audio profile + the music-presence heuristic with its evidence."""
    if not a.has_audio:
        return ["## Audio", "", "_No audio stream._", ""]
    music = a.music
    lines = [
        "## Audio", "",
        "| Metric | Value |", "|---|---|",
        f"| Integrated | {a.integrated_lufs} LUFS |",
        f"| True peak | {a.true_peak_dbtp} dBTP |",
        f"| Loudness floor (p10) | {a.loudness_floor_lufs} LUFS |",
        f"| Loudness median (p50) | {a.loudness_p50_lufs} LUFS |",
        f"| Silence ratio | {a.silence_ratio} ({a.silence_gaps} gaps) |",
        f"| Crest factor | {a.crest_factor} dB |",
        f"| RMS level | {a.rms_level_db} dB |",
        f"| Music present? | **{music.get('label')}** "
        f"({music.get('confidence')} confidence, heuristic) |", "",
        "_Music call is a heuristic, not a classifier:_",
        *[f"- {r}" for r in music.get("reasons", [])], "",
    ]
    return lines


def _transcript_section(t: dict | None) -> list[str]:
    """Speech rate + hook line, when --transcribe was used."""
    if not t:
        return []
    if t.get("skipped"):
        return ["## Speech", "", f"_Transcription skipped: {t['skipped']}._", ""]
    return [
        "## Speech", "",
        "| Metric | Value |", "|---|---|",
        f"| Words | {t.get('wordCount')} |",
        f"| Words / min | {t.get('wpm')} |",
        f"| Language | {t.get('language')} |", "",
        f"**Hook (first 3s):** {t.get('hookText') or '_(none)_'}", "",
    ]


def _review_checklist(states: list[StudyState]) -> list[str]:
    """Brain-facing: what to classify from each representative JPG."""
    lines = [
        "## VISION REVIEW CHECKLIST", "",
        "Vision-review each representative in `states/` and classify — this is "
        "how the brain learns the reference's rules of the road:", "",
        "For **every** state below, record: **layout archetype** (full-face / "
        "text-overhead / split-critique / blurpad-screen / other), **graphics "
        "present?** (stat card / list build / chip row / kinetic quote / lower "
        "third / none), **caption style** (position, size, karaoke?), **text "
        "proportion** (roughly what fraction of frame is text/graphics vs "
        "face/footage).", "",
    ]
    for s in states:
        rep = s.rep_path.split("/states/")[-1]
        hint = ("screen/graphics-heavy" if s.busy_frac >= 0.35 else
                "talking-head-like" if s.face_prominent else "sparse/other")
        lines.append(
            f"- **state {s.index}** (t={s.t_start:.1f}s, {s.duration:.1f}s, "
            f"signal: {hint}) — `states/{rep}`")
    lines.append("")
    return lines


def render_report(fingerprint: dict, pacing: PacingStats, states: list[StudyState],
                  audio: AudioProfile, transcript: dict | None) -> str:
    """Build the human-readable report.md string."""
    header = [
        f"# STUDY fingerprint — {fingerprint.get('video')}", "",
        f"- **Generated:** {fingerprint.get('generatedAt')}",
        f"- **Params:** fps={fingerprint['params']['fps']}, "
        f"dedup={fingerprint['params']['dedupThreshold']}, "
        f"scdet={fingerprint['params']['scdetThreshold']}",
        f"- **States:** {len(states)} · **Cuts:** {pacing.cut_count} · "
        f"**Cuts/min:** {pacing.cuts_per_min}", "",
    ]
    body = (_pacing_table(pacing) + _timeline_strip(states) + _audio_section(audio)
            + _transcript_section(transcript) + _review_checklist(states))
    return "\n".join(header + body) + "\n"
