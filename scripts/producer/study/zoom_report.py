#!/usr/bin/env python3
"""zoom_report — render a study_zoom map into a human-readable markdown table.

Pure formatting: takes the ``zoom_map`` dict produced by ``study_zoom`` and lays
out the cadence stats, the full zoom-event table (each event × the words spoken
at that moment), and the cutaway/b-roll map. The RULE extraction (do zooms land
on emphasis? topic shifts?) is a reading of this table and lives in the doc.
"""

from __future__ import annotations


def _mmss(t: float) -> str:
    """Seconds → m:ss.s for a scannable timestamp column."""
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _event_row(ev: dict) -> str:
    kind = "PUNCH" if ev["kind"] == "punch_in_cut" else "ramp"
    arrow = "▲in" if ev["direction"] == "in" else "▼out"
    dur = f"{ev['ramp_dur']:.1f}s" if ev["ramp_dur"] else "cut"
    said = (ev["said"][:70] + "…") if len(ev["said"]) > 71 else ev["said"]
    return (f"| {_mmss(ev['t'])} | {kind} | {arrow} | {ev['scale_pct']:+.1f}% "
            f"| {dur} | {ev['inliers']} | {said} |")


def _cadence_block(c: dict) -> list[str]:
    ratio = c["inOutRatio"] if c["inOutRatio"] is not None else "n/a"
    return [
        "## Zoom cadence",
        "",
        f"- **Events:** {c['events']} ({c['eventsPerMin']}/min) — "
        f"{c['punchInCuts']} punch-in cuts, {c['ramps']} animated ramps",
        f"- **Direction:** {c['in']} in : {c['out']} out (ratio {ratio})",
        f"- **Magnitude (linear scale):** min {c['scalePctMin']:.1f}% · "
        f"median {c['scalePctMedian']:.1f}% · max {c['scalePctMax']:.1f}%",
        f"- **Shots:** {c['talkingHeadShots']} talking-head, {c['cutawayShots']} cutaway",
        "",
    ]


def _events_table(events: list[dict]) -> list[str]:
    lines = ["## Zoom events × spoken context", "",
             "| Time | Type | Dir | Scale | Ramp | Inliers | Said around it |",
             "|---|---|---|---|---|---|---|"]
    lines += [_event_row(e) for e in events]
    lines.append("")
    return lines


def _cutaway_table(cutaways: list[dict]) -> list[str]:
    lines = ["## Cutaway / b-roll segments (talking head replaced)", "",
             "| Start | End | Duration | Shots | Kinds |", "|---|---|---|---|---|"]
    for c in cutaways:
        lines.append(f"| {_mmss(c['start'])} | {_mmss(c['end'])} | {c['duration']:.1f}s "
                     f"| {c['shots']} | {', '.join(c['kinds'])} |")
    lines.append("")
    return lines


def render_zoom_md(zoom_map: dict) -> str:
    """Full markdown report for a zoom map."""
    head = [
        f"# ZOOM MAP — {zoom_map['video'].split('/')[-1]}", "",
        f"- Duration {zoom_map['duration']}s · sampled {zoom_map['fps']}fps · "
        f"scdet {zoom_map['scdet']} → {zoom_map['cutCount']} cut boundaries",
        f"- Scale via ORB similarity (|scale-1| noise floor ~0.2% on the raw "
        f"locked camera); ramp gate {zoom_map['config']['ramp_scale_min'] * 100:.0f}% "
        f"linear, punch gate {zoom_map['config']['punch_scale_min'] * 100:.0f}%",
        "",
    ]
    return "\n".join(head + _cadence_block(zoom_map["cadence"])
                     + _events_table(zoom_map["events"])
                     + _cutaway_table(zoom_map["cutaways"]))
