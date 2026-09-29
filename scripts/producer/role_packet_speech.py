"""A plan's on-screen title and kept speech compared with a verified given title and script.

Requirement revision `approved-content-production-2026-09-27`. Separate facts, never one "matches":
the title (exact, normalization-only or different), the selection (which admitted-transcript words,
in which order, from which source and transcript version), the caption text (the source word each
kept occurrence carries; declared display corrections are listed with their display text and whether
they change a given word's displayed spelling, never counted as mismatches) and the timing (each
occurrence's frames under the writer's exact rule, its segment's cut, and the plan's cut seconds
against the given seconds). Each is {matches, details}. All are identity or arithmetic facts for
the critic; none judges whether the given content is good.
"""
from __future__ import annotations

from role_packet_approvals import compare_titles, expand_words
from role_packet_transcript import Transcript, occurrence_frames
from studio.native_budget_selection import merged

SAMPLE = 64


def planned_title(plan: dict) -> str | None:
    """The plan's on-screen title text as the writer mounts it: the built-in titleCard copy, else catalogTitle's."""
    canvas = plan.get("canvas") if isinstance(plan.get("canvas"), dict) else {}
    for holder in (canvas.get("titleCard"), plan.get("catalogTitle")):
        copy = holder.get("copy") if isinstance(holder, dict) else None
        if isinstance(copy, dict) and isinstance(copy.get("text"), str):
            return copy["text"]
    return None


def planned_source(plan: dict) -> str | None:
    """SHA-256 of the canvas source asset."""
    canvas = plan.get("canvas") if isinstance(plan.get("canvas"), dict) else {}
    return next((row.get("sha256") for row in plan.get("assets", []) if isinstance(row, dict)
                 and row.get("file") == canvas.get("sourceFile") and row.get("role") == "source"), None)


def kept(plan: dict) -> list[list]:
    """Well-formed occurrence tuples in output order."""
    rows = (plan.get("canvas") or {}).get("occurrences") or []
    return [row for row in rows if isinstance(row, list) and len(row) >= 7
            and all(isinstance(row[index], int) and not isinstance(row[index], bool) for index in (0, 1, 2, 3, 4))]


def plan_selection(plan: dict) -> dict | None:
    """The plan's source and merged cut seconds (the authority's selection form), or None when it cuts nothing."""
    cuts = [[cut["start"], cut["end"]] for cut in (plan.get("canvas") or {}).get("cuts") or []
            if isinstance(cut, dict) and all(isinstance(cut.get(key), (int, float)) for key in ("start", "end"))
            and cut["end"] > cut["start"]]
    source = planned_source(plan)
    return {"source": source, "ranges": merged(cuts)} if source and cuts else None


def selection(row: dict, plan: dict, transcript: Transcript, words: list[int]) -> dict:
    """Same source, same transcript version and exactly the given words in the given order, once each."""
    approved, count = expand_words(row["wordRanges"]), len(transcript.words)
    seen: dict[int, int] = {}
    for word in words:
        seen[word] = seen.get(word, 0) + 1
    order = list(dict.fromkeys(words))
    details = {"sourceMatches": planned_source(plan) == row["source"], "transcriptMatches": row["transcript"] == transcript.sha256,
               "missingWords": sorted(set(approved) - set(words))[:SAMPLE],
               "extraWords": sorted(set(words) - set(approved))[:SAMPLE],
               "outOfRangeWords": sorted(word for word in seen if not 0 <= word < count)[:SAMPLE],
               "repeatedWords": sorted(word for word, times in seen.items() if times > 1)[:SAMPLE],
               "otherOrder": set(order) == set(approved) and order != approved}
    matches = details["sourceMatches"] and details["transcriptMatches"] and order == approved and not details["repeatedWords"]
    return {"matches": matches, "details": details}


def display_corrections(row: dict, plan: dict, occurrences: list[list]) -> list[dict]:
    """Declared caption display corrections beside the given word each displays differently."""
    given = dict(zip(expand_words(row["wordRanges"]), row["wordTexts"]))
    by_id = {occ[0]: occ for occ in occurrences}
    rows = [item for item in (plan.get("canvas") or {}).get("captionCorrections") or [] if isinstance(item, dict)]
    result = []
    for item in rows[:SAMPLE]:
        occ = by_id.get(item.get("occurrenceId"))
        word = occ[2] if occ else None
        result.append({"occurrenceId": item.get("occurrenceId"), "sourceWord": word, "sourceText": occ[5] if occ else None,
                       "givenText": given.get(word), "displayText": item.get("displayText"), "reason": item.get("reason"),
                       "changesGivenSpelling": None if word not in given else item.get("displayText") != given[word]})
    return result


def caption_text(row: dict, plan: dict, transcript: Transcript, occurrences: list[list]) -> dict:
    """Each kept occurrence carries its source word's transcript text; display corrections are listed, not mismatches."""
    count = len(transcript.words)
    wrong = [occ[0] for occ in occurrences if not 0 <= occ[2] < count or occ[5] != transcript.words[occ[2]]["text"]]
    return {"matches": not wrong, "details": {"mismatchedOccurrences": wrong[:SAMPLE],
                                              "displayCorrections": display_corrections(row, plan, occurrences)}}


def timing(row: dict, plan: dict, transcript: Transcript, occurrences: list[list]) -> dict:
    """Occurrence frames under the writer's rule, each word inside its segment's cut, and cut seconds."""
    canvas = plan.get("canvas") or {}
    derived = [(occ, occurrence_frames(occ, canvas, transcript.words)) for occ in occurrences]
    unmapped = [occ[0] for occ, frames in derived if frames is None]
    moved = [occ[0] for occ, frames in derived if frames is not None and frames != (occ[3], occ[4], occ[6])]
    chosen = plan_selection(plan)
    seconds = chosen is not None and chosen["ranges"] == merged([list(item) for item in row["ranges"]])
    return {"matches": not unmapped and not moved and seconds,
            "details": {"cutSecondsMatchGivenSeconds": seconds, "segmentMismatches": unmapped[:SAMPLE],
                        "frameMismatches": moved[:SAMPLE]}}


def comparison(row: dict, plan: dict, transcript: Transcript) -> dict:
    """Title, selection, caption text and timing facts for one verified given row against the plan."""
    title = planned_title(plan)
    # A title is always handed over with the script (the authority refuses a missing one); a legacy row without
    # one cannot be matched, so the plan's title is a departure, never an agent-authored substitute.
    state = compare_titles(row["title"], title) if row["title"] is not None else "different"
    occurrences = kept(plan)
    words = [occ[2] for occ in occurrences]
    return {"title": {"given": row["title"], "planned": title, "status": state, "material": state == "different"},
            "selection": selection(row, plan, transcript, words),
            "captionText": caption_text(row, plan, transcript, occurrences),
            "timing": timing(row, plan, transcript, occurrences)}
