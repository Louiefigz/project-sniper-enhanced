"""The engine-observed half of shared-evidence schema version 2 (P2-07): approvals, coverage and speaker observations.

Nothing here is authored. At seal, ``--batch B`` names the one active or draining batch. Every clip's current
approval is read from the batch authority (``studio.production.api.read_approval``, the only source of approved
scripts) and recomputed against the observed transcript (``role_packet_approvals.verified_row``). The midpoint of
each retained word must lie in exactly one speaker interval of its source; intervals are half-open
``[startSeconds, endSeconds)``, so touching intervals never share a midpoint.

The bound ``speaker-observations`` file is the completed inspection reference P2-06 publishes
(``SPEAKER-OBSERVATIONS.json``: ``{path, sha256, owner, ownerSha256}``; X59). Its record is read with
``read_inspection(..., require_owner_digest=True)``. The record's source must be one this evidence admits, and it
is this record's source. The record covers the listed clips (X127): the batch's clips approved on that source.
Clips approved on another source are outside this record, and another record may cover them; a batch drawn from
two sources is never refused. The observations must be measured on each listed clip's approved transcript (X68)
and hold exactly the listed scripts in ``clipId`` order (X59).

Faces map to people through ``faceRegion``: a face belongs to the one person whose ``xRange`` holds its centre x
(a centre in no region, or in two, belongs to nobody). This is the measurement P2-06's 90% stop needs (X59(7)).
Per person with a region on the observed source the record keeps the sampled frames holding that person's face,
the sampled frames (the denominator, P2:666) and their ratio. Nothing here refuses on those numbers: the stop is
a one-time plan stop on IMG_5954, read at M-071v/M-077v (X127).

The authority and inspection readers are imported where they are used. Version 1 checks never reach them, so they
load exactly the modules they load today.
"""
from __future__ import annotations

from fractions import Fraction

from cut_preview_io import bound_json
from role_packet_approvals import CANONICAL_FORM, expand_words, verified_row
from role_packet_evidence_schema import EvidenceError
from role_packet_files import canonical_file
from role_packet_transcript import Transcript, exact

OBSERVATIONS_KEY = "speaker-observations"
OBSERVATIONS_KIND = "sniper-speaker-observations"
REFERENCE_KEYS = frozenset({"path", "sha256", "owner", "ownerSha256"})
LIVE = ("active", "draining")
FORM = CANONICAL_FORM.split(":", 1)[0] + ":"


def clip_approval(batch: str, clip: str, live: bool) -> dict:
    """One clip's current approval-v2 row from the batch authority, as ``{clipId, **row}``.

    Args:
        batch: The batch id.
        clip: The clip id.
        live: Also require the batch to be active or draining (at seal).

    Raises:
        EvidenceError: An unreadable authority, no current approval, a closed batch where one must be live, or
            another canonical form.
    """
    from studio import native_budget_store
    from studio.production import api as authority
    try:
        found = authority.read_approval(native_budget_store.default_root(), batch, clip)
    except (RuntimeError, OSError) as error:
        raise EvidenceError(f"batch {batch} clip {clip}'s approval cannot be read: {error}") from error
    if not isinstance(found, dict) or found.get("current") is None:
        raise EvidenceError(f"batch {batch} clip {clip} has no approved title/script for the speaker facts to cover")
    if live and found.get("status") not in LIVE:
        raise EvidenceError(f"batch {batch} is {found.get('status')}; coverage is sealed against an active or draining batch")
    if not str(found.get("canonicalForm", "")).startswith(FORM):
        raise EvidenceError(f"batch {batch} clip {clip}'s approval is not in {FORM[:-1]} form")
    return {"clipId": clip, **found["current"]}


def batch_approvals(batch: str) -> list[dict]:
    """At seal: every clip's current approval in batch B, which must be the one active or draining batch.

    Returns:
        ``{clipId, **approval row}`` per clip, in clipId order.
    """
    from studio import native_budget_store
    from studio.native_budget_batches import current_batches
    try:
        records = dict(current_batches(native_budget_store.default_root()))
    except (RuntimeError, OSError) as error:
        raise EvidenceError(f"the batch authority cannot be read: {error}") from error
    if list(records) != [native_budget_store.require_batch_id(batch)]:
        raise EvidenceError(f"batch {batch} is not the current active or draining batch ({sorted(records) or 'none is'}); "
                            "coverage binds only the current batch's approvals")
    clips = sorted(records[batch].get("clips") or {})
    if not clips:
        raise EvidenceError(f"batch {batch} has no clips whose approved scripts the speaker facts could cover")
    return [clip_approval(batch, clip, True) for clip in clips]


def sealed_approvals(batch: object, clips: list[str]) -> list[dict]:
    """At bind: the sealed clips' current approvals, whatever the batch's status now (archived batches too)."""
    from studio import native_budget_store
    return [clip_approval(native_budget_store.require_batch_id(batch), clip, False) for clip in clips]


def uncovered(clip: str, bounds: list[tuple[Fraction, Fraction]], transcript: Transcript, ranges: list) -> None:
    """Refuse the first retained word whose midpoint lies in two intervals, or the first run it lies in none of."""
    run: list[int] = []
    for index in expand_words(ranges):
        word = transcript.words[index]
        middle = (exact(word["start"]) + exact(word["end"])) / 2
        holders = sum(1 for start, end in bounds if start <= middle < end)
        if holders > 1:
            raise EvidenceError(f"speaker intervals overlap at {float(middle):g} s")
        if holders == 0 and (not run or run[-1] == index - 1):
            run.append(index)
        elif run:
            break
    if run:
        first, last = transcript.words[run[0]], transcript.words[run[-1]]
        raise EvidenceError(f"speaker facts do not cover clip {clip} source words {run[0]}-{run[-1]} "
                            f"({first['start']}-{last['end']} s)")


def coverage(value: object, approvals: list[dict], words: dict) -> dict:
    """At seal and at bind: each approved clip's retained words, each midpoint inside exactly one interval.

    Args:
        value: The validated version 2 speaker intervals.
        approvals: ``{clipId, **approval row}`` per listed clip (``listed_approvals``).
        words: ``{sourceSha256: (source id, observed Transcript)}`` for the sources the approvals are on.

    Returns:
        ``{"clips": [{clipId, scriptIdentity, wordRanges}]}`` in clipId order; each identity is recomputed.

    Raises:
        EvidenceError: A gap or an overlap.
        ApprovalError: An approval that does not recompute against the observed transcript.
    """
    clips = []
    for approval in sorted(approvals, key=lambda row: row["clipId"]):
        source, transcript = words[approval["source"]]
        row = verified_row(approval, transcript, derived_seconds=False)
        bounds = [(exact(item["startSeconds"]), exact(item["endSeconds"])) for item in value if item["source"] == source]
        uncovered(approval["clipId"], bounds, transcript, approval["wordRanges"])
        clips.append({"clipId": approval["clipId"], "scriptIdentity": row["script"], "wordRanges": approval["wordRanges"]})
    return {"clips": clips}


def observation_record(bound: dict) -> tuple[dict, dict]:
    """(reference, record) of the bound speaker observations, read through the inspection reader.

    Raises:
        EvidenceError: Nothing bound as ``speaker-observations``, a file that is not the reference, or an inspection
            that did not complete with an owner-captured result digest.
    """
    from studio.owned_inspection import read_inspection
    row = bound.get(OBSERVATIONS_KEY)
    if row is None:
        raise EvidenceError(f"v2 speaker intervals need the speaker observations bound: --bind {OBSERVATIONS_KEY}="
                            "<output>/SPEAKER-OBSERVATIONS.json (P2-06)")
    try:
        reference = bound_json(canonical_file(row["path"]), row["sha256"])
        if set(reference) != REFERENCE_KEYS:
            raise ValueError(f"the reference must hold exactly {sorted(REFERENCE_KEYS)}")
        record = read_inspection(reference, require_owner_digest=True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        raise EvidenceError(f"{OBSERVATIONS_KEY} is not a completed speaker-observation inspection: {error}") from error
    if record.get("schemaVersion") != 1 or record.get("kind") != OBSERVATIONS_KIND:
        raise EvidenceError(f"{OBSERVATIONS_KEY} holds no {OBSERVATIONS_KIND} record")
    return reference, record


def face_owner(face: dict, regions: dict) -> str | None:
    """The one person whose face region holds this face's centre x, or None (in no region, or in two)."""
    centre = face["x"] + face["w"] / 2
    owners = [person for person, (low, high) in regions.items() if low <= centre <= high]
    return owners[0] if len(owners) == 1 else None


def face_row(person: str, frames: list[dict], regions: dict) -> dict:
    """One person's measurement: sampled frames holding their face, all sampled frames, and the ratio (or null)."""
    found = sum(1 for frame in frames if person in {face_owner(face, regions) for face in frame["faces"]})
    return {"person": person, "framesWithFace": found, "framesSampled": len(frames),
            "ratio": found / len(frames) if frames else None}


def face_coverage(record: dict, people: list[dict], source: str) -> list[dict]:
    """Per person with a face region on the observed source, P2-06's measurement (X59(7)); it never refuses.

    The denominator is every sampled frame of the record, including frames where no face was found (P2:666).
    M-071v/M-077v compare these numbers with 90% on IMG_5954 and stop the plan below it (X127, ST-4).
    """
    regions = {row["id"]: tuple(row["faceRegion"]["xRange"]) for row in people
               if (row.get("faceRegion") or {}).get("source") == source}
    return [face_row(person, record["faces"], regions) for person in sorted(regions)]


def measured_source(record: dict, sources: list[dict]) -> tuple[str, str]:
    """(sourceSha256, admitted source id) of the source the speaker observations measured.

    Raises:
        EvidenceError: The observations describe a source this evidence does not admit.
    """
    observed = record.get("source") if isinstance(record.get("source"), dict) else {}
    measured = str(observed.get("sourceSha256"))
    source = {row["sourceSha256"]: row["id"] for row in sources}.get(measured)
    if source is None:
        raise EvidenceError(f"speaker observations describe source {measured[:12]}, which this evidence does not admit")
    return measured, source


def listed_approvals(context: dict) -> list[dict]:
    """The clips this record covers (X127): the batch's clips approved on the source the observations measured.

    Args:
        context: ``bound`` (key to observed file row), ``sources`` and ``approvals`` (the batch's clips).

    Returns:
        The listed approvals. Clips on any other source are outside this record, never a refusal.

    Raises:
        EvidenceError: Observations of a source this evidence does not admit, or no clip on the measured source.
    """
    _reference, record = observation_record(context["bound"])
    measured, _source = measured_source(record, context["sources"])
    listed = [row for row in context["approvals"] if row.get("source") == measured]
    if not listed:
        raise EvidenceError(f"no clip of the batch is approved on source {measured[:12]}, which the speaker "
                            "observations measured; nothing for this record to cover")
    return listed


def observations_binding(context: dict, coverage: dict) -> dict:
    """The bound speaker observations must measure exactly the covered scripts, on their approved transcripts.

    Args:
        context: ``bound`` (key to observed file row), ``sources``, ``approvals`` (the listed clips) and ``people``.
        coverage: What ``coverage`` returned for those clips.

    Returns:
        ``{reference, faceCoverage}``: the published inspection reference and ``face_coverage``'s rows.
    """
    reference, record = observation_record(context["bound"])
    _measured, source = measured_source(record, context["sources"])
    heard = str((record.get("source") or {}).get("transcriptSha256"))
    for approval in context["approvals"]:
        if approval["transcript"] != heard:
            raise EvidenceError(f"speaker observations were measured on transcript {heard[:12]}, not clip "
                                f"{approval['clipId']}'s approved transcript {str(approval['transcript'])[:12]}")
    if record.get("scripts") != coverage["clips"]:
        measured_clips = [row.get("clipId") for row in record.get("scripts") or [] if isinstance(row, dict)]
        raise EvidenceError("speaker observations measured other scripts than the covered clips, compared in clipId "
                            f"order: {measured_clips} vs {[row['clipId'] for row in coverage['clips']]}")
    return {"reference": reference, "faceCoverage": face_coverage(record, context["people"], source)}
