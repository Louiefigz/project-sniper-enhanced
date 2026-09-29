"""Operator-approved content at hand-off: read only from the batch authority, compared exactly, never re-approved.

Requirement revision ``approved-content-production-2026-09-27``. ``native_handoff_approval`` reads the approval
the delivery answers (by the export's own ``productionBudget`` batch clip, confirmed by the folder's binding).

The build is read as B1 reads a plan (``role_packet_approvals``/``role_packet_speech``): the title is the
``catalogTitle`` copy, else the built-in ``canvas.titleCard`` copy; the script is the canvas source asset and the
source word index and text of every kept ``canvas.occurrences`` row, in output order. The approved script is the
spoken words, so word texts are each occurrence's SOURCE text (``occurrences[*][5]``, which
``canvas.captionCorrections`` never rewrite), never displayed caption text; accepted caption corrections
(occurrenceId, source text, display text, reason) are listed as ``displayCorrections`` (beyond the cap, counted in
``displayCorrectionsOmitted``) and are not a mismatch. Rules follow A12's approval-v2 comparison: the title is
exact, normalization-only (NFC and whitespace; reported, not material) or different; the script is the source,
the ordered word indices (the same words in another order differ), the word texts, the cut seconds (the plan's
merged cuts against the approval's merged second ranges), the transcript (the plan's admitted manifest transcript
against the approval's) and the occurrence timing under the writer's rule (``role_packet_speech.timing``).
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from cut_preview_io import bound_json
from role_packet_files import ArtifactError
from role_packet_given import plan_transcript
from role_packet_speech import kept, plan_selection, timing
from studio.native_budget_selection import merged
from studio.native_handoff_approval import authority_approval

TEXT_FIELD, WORD_FIELD, SAMPLE, CORRECTIONS = 5, 2, 20, 128
DISTINCTION = ('operatorApproval is the operator\'s approval of the title words and script, bound at batch start; '
               'output.executionReview covers only this render\'s visual and technical execution.')
MATERIAL = ('titleMatchesApproval', 'sourceMatchesApproval', 'wordsMatchApproval', 'wordTextsMatchApproval',
            'secondsMatchApproval', 'transcriptMatchesApproval', 'timingMatchesApproval')


def read_plan(project: Path) -> dict | None:
    """The delivered project's plan, or None when it is not a native Short project."""
    file = project / 'SHORT-PROJECT.json'
    return bound_json(file) if file.is_file() else None


def planned(plan: dict | None) -> dict:
    """The title and script this project executes, read as B1's planned_title/planned_script read a plan."""
    if plan is None:
        return {'title': None, 'source': None, 'words': None, 'texts': None, 'displayCorrections': [],
                'displayCorrectionsOmitted': 0, 'reason': 'not a native Short project'}
    canvas = plan.get('canvas') if isinstance(plan.get('canvas'), dict) else {}
    copies = [holder.get('copy') for holder in (plan.get('catalogTitle'), canvas.get('titleCard'))
              if isinstance(holder, dict) and isinstance(holder.get('copy'), dict)]
    title = next((copy['text'] for copy in copies if isinstance(copy.get('text'), str)), None)
    source = next((row.get('sha256') for row in plan.get('assets', []) if isinstance(row, dict)
                   and row.get('file') == canvas.get('sourceFile') and row.get('role') == 'source'), None)
    rows = [row for row in canvas.get('occurrences') or [] if isinstance(row, list) and len(row) > TEXT_FIELD]
    corrections = display_corrections(canvas, rows)
    return {'title': title, 'source': source, 'words': [row[WORD_FIELD] for row in rows],
            'texts': [row[TEXT_FIELD] for row in rows], 'displayCorrections': corrections[:CORRECTIONS],
            'displayCorrectionsOmitted': max(0, len(corrections) - CORRECTIONS)}


def _correction(row: dict, by_id: dict[int, list]) -> dict:
    """One accepted display correction beside the source word and text it displays differently."""
    word = by_id.get(row.get('occurrenceId')) or []
    return {'occurrenceId': row.get('occurrenceId'), 'sourceWord': word[WORD_FIELD] if word else None,
            'sourceText': word[TEXT_FIELD] if word else None, 'expectedSourceText': row.get('expectedSourceText'),
            'displayText': row.get('displayText'), 'reason': row.get('reason')}


def display_corrections(canvas: dict, rows: list[list]) -> list[dict]:
    """Every accepted caption display correction (reported, never compared with the approved spoken words)."""
    by_id = {row[0]: row for row in rows}
    return [_correction(row, by_id) for row in canvas.get('captionCorrections') or [] if isinstance(row, dict)]


def compare_titles(approved: str | None, observed: str | None) -> str:
    """'exact', 'normalization-only' (NFC and collapsed/trimmed whitespace only; not material) or 'different'."""
    if approved == observed:
        return 'exact'
    if approved is None or observed is None:
        return 'different'
    fold = [' '.join(unicodedata.normalize('NFC', text).split()) for text in (approved, observed)]
    return 'normalization-only' if fold[0] == fold[1] else 'different'


def expand_words(word_ranges: list[list[int]]) -> list[int]:
    """Inclusive [first, last] word ranges as the ordered index list."""
    return [word for first, last in word_ranges for word in range(first, last + 1)]


def _seconds_and_transcript(row: dict, plan: dict) -> dict:
    """The plan's merged cut seconds, its admitted transcript and the writer-rule timing against the approval."""
    selection = plan_selection(plan)
    try:
        transcript = plan_transcript(plan)
    except ArtifactError as error:
        transcript, reason = None, str(error)[:300]
    else:
        reason = None
    same = transcript is not None and transcript.sha256 == row['transcript']
    return {'secondsMatchApproval': selection is not None and selection['ranges'] == merged([list(item) for item in row['ranges']]),
            'transcriptMatchesApproval': same, 'transcriptProblem': reason,
            'timingMatchesApproval': same and timing(row, plan, transcript, kept(plan))['matches']}


def _comparisons(row: dict, shown: dict, plan: dict) -> dict:
    """The approval-v2 rules applied to one build."""
    approved_words = expand_words(row['wordRanges'])
    title = compare_titles(row['title'], shown['title'])
    return {'title': title, 'titleMatchesApproval': title != 'different',
            'sourceMatchesApproval': shown['source'] == row['source'],
            'wordsMatchApproval': shown['words'] == approved_words,
            'wordTextsMatchApproval': shown['texts'] == row['wordTexts'],
            'sameWordsOtherOrder': sorted(shown['words']) == sorted(approved_words) and shown['words'] != approved_words,
            'missingWords': sorted(set(approved_words) - set(shown['words']))[:SAMPLE],
            'extraWords': sorted(set(shown['words']) - set(approved_words))[:SAMPLE], **_seconds_and_transcript(row, plan)}


def section(project: Path, production: dict | None) -> dict:
    """The authority's approval, the build and the exact comparisons; a mismatch is reported, never repaired."""
    (given, problem), plan = authority_approval(project, production), read_plan(project)
    shown = planned(plan)
    result = dict.fromkeys(['title', *MATERIAL, 'sameWordsOtherOrder', 'missingWords', 'extraWords', 'transcriptProblem'])
    if given['status'] == 'supplied' and plan is not None:
        result.update(_comparisons(given['approval'], shown, plan))
    clip = (production or {}).get('clipId')
    bound = given['status'] == 'supplied' and clip is not None
    return {'operatorApproval': given, 'approvalBinding': {'problem': problem}, 'built': shown,
            'displayCorrections': shown['displayCorrections'], 'displayCorrectionsOmitted': shown['displayCorrectionsOmitted'],
            'production': production, 'distinction': DISTINCTION,
            'clipMatchesApproval': (given['clipId'], given['batchId']) == (clip, production.get('batchId'))
            if bound else None, **result}


def mismatches(content: dict) -> list[str]:
    """Which material approved-content comparisons failed (empty when none was compared or all held)."""
    return [key for key in (*MATERIAL, 'clipMatchesApproval') if content[key] is False]
