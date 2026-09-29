"""Human-readable briefing for a published role packet; the JSON file stays authoritative."""
from __future__ import annotations

import json
from pathlib import Path


def instruction_lines(packet: dict) -> list[str]:
    """Every governing file with its hash and the exact line ranges to read, then what was not assigned."""
    lines = ["Governing instructions (read these ranges completely; hashes are frozen in the packet):"]
    for row in (row for row in packet["instructions"] if row["sections"]):
        ranges = "; ".join(f"{section['startLine']}-{section['endLine']} {section['title'][:70]}"
                           for section in row["sections"])
        lines.append(f"  [{row['read']}] {row['path']} (sha256 {row['sha256'][:12]}) — {ranges}")
    excluded = [(row["path"], item) for row in packet["instructions"] for item in row.get("excluded", [])]
    if excluded:
        lines.append("Not assigned to this role and subject by the maintained catalog (reason recorded; read one if the "
                     "subject actually uses what it governs):")
        lines += [f"  {Path(path).name} {item['startLine']}-{item['endLine']}: {item['reason'][:110]}"
                  for path, item in excluded]
    return lines


def evidence_lines(packet: dict) -> list[str]:
    """The bound shared evidence: its engine-observed facts, authored claims and limits (the record is authoritative)."""
    evidence = packet.get("sharedEvidence")
    if not evidence:
        return ["Shared evidence: none bound (derive source, speaker and reference facts yourself)."]
    claims = evidence["authoredClaims"]
    lines = [f"Shared evidence v{evidence['version']}: {evidence['path']} (sha256 {evidence['sha256'][:12]}), "
             f"author {evidence['author']['sessionId']}",
             f"  Engine-observed (reusable): manifest {evidence['engineObserved']['manifest'][:12]}, "
             f"{len(evidence['engineObserved']['sources'])} source(s), transcripts "
             + ", ".join(f"{key} {value[:12]}" for key, value in evidence["engineObserved"]["transcripts"].items()),
             f"  Authored claims (check and dispute): {claims['sourceScanFacts']} scan facts, {claims['people']} people, "
             f"{claims['intervals']} intervals, listening {claims['listening']}, reference {claims['reference']}, "
             f"decisions {', '.join(claims['decisions']) or 'none'}"]
    if evidence["authoredByRecordedAuthor"]:
        lines.append("  WARNING the shared evidence was authored by a recorded author of this work: verify it as a claim.")
    return lines + [f"  Limit: {text[:150]}" for text in evidence["limits"]]


def given_lines(given: dict) -> list[str]:
    """The authority's given title and script and the plan's separate title, selection, caption-text and timing facts."""
    if given["status"] != "bound":
        return [f"Given title/script: {given['status']} ({given['meaning']})"]
    lines = [f"Given title/script: batch {given['batchId']} clip {given['clipId']} (from {given['readFrom']}; identity "
             f"{str(given['identity'])[:12]}): title {given['title']['given']!r}"]
    if not given["planChecked"]:
        return lines + ["  Not compared: no plan in this packet."]
    title = given["title"]
    lines.append(f"  Title: plan {title['planned']!r} -> {title['status']} (material {title['material']})")
    for key in ("selection", "captionText", "timing"):
        fact = given[key]
        lines.append(f"  {key}: matches {fact['matches']} {json.dumps(fact['details'], ensure_ascii=False)[:400]}")
    return lines


def reading_lines(packet: dict) -> list[str]:
    """How each frozen artifact is used, with located index entries."""
    counts: dict[str, int] = {}
    for row in packet["artifacts"]:
        counts[row.get("read", "inspect")] = counts.get(row.get("read", "inspect"), 0) + 1
    lines = [f"Frozen artifacts: {len(packet['artifacts'])} files ("
             + ", ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
             + f"); large media listed without rehash: {len(packet['declaredMedia'])} (paths and hashes in the JSON)."]
    for row in (row for row in packet["artifacts"] if "entries" in row):
        entries = ", ".join(f"{entry['id']} ({entry['pointer']})" for entry in row["entries"]) or "none located"
        missing = f"; NOT FOUND: {', '.join(row['missingEntries'])}" if row["missingEntries"] else ""
        verb = "Consult only" if row["read"] == "entries" else "Search the complete index; start with"
        lines.append(f"  {verb} {Path(row['path']).name} entries {entries}{missing}")
    return lines


def size_line(packet: dict) -> str:
    """The packet's recorded size and reading estimate."""
    size = packet["size"]
    instructions, estimate = size["instructions"], size["estimatedReadingTokens"]
    return (f"Size: packet {size['packetBytes']} bytes; {instructions['sections']} sections, {instructions['lines']} lines "
            f"({instructions['excludedSections']} excluded, {instructions['excludedLines']} lines); about "
            f"{estimate['total']} reading tokens assigned (bytes/4 estimate, not review time).")


def frame_line(row: dict) -> str:
    """One frame window with its time bounds."""
    return (f"frames {row['startFrame']}–{row['endFrameExclusive']} "
            f"({row['startSeconds']:.3f}–{row['endSeconds']:.3f} s)")


def media_lines(subject: dict) -> list[str]:
    """Windows to play, preview gaps and program events for motion/final critics."""
    lines = [f"  Window {row['index']}: {frame_line(row)} — {row['path']}" for row in subject.get("windows", [])]
    coverage = subject.get("previewCoverage") or {}
    if coverage.get("status") == "unavailable":
        lines.append(f"  Preview coverage UNKNOWN (preview evidence unavailable): {coverage.get('reason')}")
    lines += [f"  Not shown by moving previews: {frame_line(row)}" for row in subject.get("uncovered") or []]
    marks = {True: "", False: " [outside previews]", None: " [preview coverage unknown]"}
    lines += [f"  Event frame {row['frame']} ({row['seconds']:.3f} s): {', '.join(row['labels'])}"
              f"{marks[row['coveredByPreview']]}" for row in subject.get("events", [])]
    lines += [f"  Nested mount without a root clock (find it in playback): {name}"
              for name in subject.get("nestedMounts", [])]
    lines += [f"  Audio QC row to review: {row.get('name')} [{row.get('status')}] {row.get('measured', '')}"
              for row in subject.get("audioReview", [])]
    return lines


def subject_lines(packet: dict) -> list[str]:
    """What exactly is under review."""
    subject = packet["subject"]
    lines = ["Subject:"]
    for key in ("plan", "preview"):
        if isinstance(subject.get(key), dict) and "path" in subject[key]:
            lines.append(f"  {key}: {subject[key]['path']} (sha256 {subject[key]['sha256'][:12]})")
    if isinstance(subject.get("export"), dict) and "video" in subject["export"]:
        video = subject["export"]["video"]
        lines.append(f"  video: {video['path']} (sha256 {video['sha256'][:12]}, {video['links']} link(s))")
    lines += [f"  Scene {row['index']}: frames {row['startFrame']}–{row['endFrame']} "
              f"({row['startSeconds']:.3f}–{row['endSeconds']:.3f} s) {row.get('format') or ''}"
              for row in subject.get("scenes", [])] if packet["role"] == "plan-critic" else []
    lines += [f"  Caption suppression {frame_line({**row, 'endFrameExclusive': row['endFrame']})}: {row['reason'][:120]} "
              f"— uncaptioned speech: {row['spokenText'][:200]!r}" for row in subject.get("captionSuppressions") or []]
    retention = subject.get("retention") or {}
    if retention.get("missingUnits"):
        lines.append(f"  WARNING reused units without a retained review row: {retention['missingUnits']} "
                     "(re-resolve with --prior-reviews <earlier MOTION-REVIEW record>)")
    return lines + media_lines(subject)


def finish_lines(packet: dict, published: dict) -> list[str]:
    """The exact typed command that completes the role."""
    submission = packet["submission"]
    if "steps" in submission:
        return ["Route steps (state is derived only from the supplied artifacts):"] + [
            f"  {row['id']} [{row['state']}]: {row['command']['shell']}" for row in submission["steps"]]
    inspection = submission.get("inspection") or {}
    lines = ["Typed inspection (record only what you actually did):", f"  {inspection.get('rule', '')}"]
    lines += [f"  Target frames {row['frames'][0]}–{row['frames'][1]}: {row['path']} (sha256 {row['sha256']})"
              for row in inspection.get("targets", [])]
    return lines + ["Finish with (write the observations first; every null field is yours to author):",
                    f"  observations: {published['observations']}",
                    f"  {submission['shell']}"]


def render_role_packet(packet: dict, published: dict) -> str:
    """Compact briefing printed by context.py --role."""
    lines = [f"ROLE PACKET — {packet['role']} ({packet['route']}, {packet['catalog']})",
             f"Packet: {published['packet']}", f"Packet sha256: {published['sha256']} (observations.rolePacketSha256)",
             f"Recorded author identities: {', '.join(packet['authorSessionIds']) or 'none recorded'}"]
    lines += ["Obligations:"] + [f"  {key}: {row['statement']} ({', '.join(row['checks'])})"
                                  for key, row in packet["obligations"].items()]
    lines += instruction_lines(packet) + evidence_lines(packet) + given_lines(packet["given"]) + subject_lines(packet)
    lines += ["Required checks:"] + [f"  {row['id']} {row['check']} [{row['source']}]" for row in packet["checks"]]
    lines += finish_lines(packet, published) + reading_lines(packet)
    lines += ["Limits:"] + [f"  {text}" for text in packet["limits"]] + [size_line(packet)]
    timing = published["timing"]
    lines.append(f"Resolved in {timing['resolveSeconds']:.3f} s; published in {timing['totalSeconds']:.3f} s.")
    return "\n".join(lines)
