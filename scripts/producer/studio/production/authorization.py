"""Production authorization: the clock starts when the operator hands over approved content, not after setup.

``authorize`` durably creates the batch record at the moment of authorization: its clock
anchor, the declared clips and every clip's approved title and script, with setup
``pending``. Only then does the caller inspect host capacity, hash the declared source
recordings and freeze the engine identity, and ``complete_setup`` records them. Setup
time is inside the batch clock (verified with a slow source hash). A failed or
interrupted setup leaves the authorization and its anchor in place; running ``start``
again with the same authorization resumes it instead of minting a new start, even past its
deadline (the batch is live; its status reports the miss), and no new work is admitted until
setup completes. Nothing here re-asks for approval.

A refused start (another batch still active or draining) keeps the authorization too: its
record, anchored at the go time, is staged as ``<root>/batches/.creating-<batch>-<12 hex>/``
(``native_budget_staging``), ignored by resolution, at most one adoptable staging per batch id
and ``MAX_STAGED`` adoptable ones in all. The next start with the same identity (batch, declared
clips, their approvals and the AI slots/reservations) publishes that staged record, so its anchor
stands, while it still leaves room for a minimal deliverable before its deadline. A rerun that
changes only the AI settings is refused by name, never a new clock; a rerun with other approved
content is a new hand-over that replaces the staging. A staging whose clock cannot be dated is left
for the operator and refuses its batch id's start by name. Every authorization that is discarded
(expired, replaced, taken or by the operator) is recorded as a miss, and the batch that finally
starts under that id lists it (``authorization.prior``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from studio.native_budget_batches import BudgetRefused, PredecessorCurrent, refuse_creation
from studio.native_budget_staging import (
    ADOPTABLE, FOREIGN, STAGING, UNPROVABLE, Staging, adoptable_stagings, assess, discard, prior_authorizations,
    publish_staged, stage_record, staging_of, stagings, sweep_stagings,
)
from studio.native_budget_binding import advance_clock
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_schema import BOUNDS
from studio.native_budget_store import (
    BudgetAuthorityError, archived_directory, batch_directory, locked_batch, read_batch, registry_lock,
    require_batch_id,
)
from studio.production.authorization_record import content_identity
from studio.production.tasks import TaskConflict

SHA256 = re.compile(r'[0-9a-f]{64}')
MAX_STAGED = 8           # adoptable staged (interrupted or refused) starts kept at once under batches/
REPLACED = 'a new hand-over of this batch id with other approved content replaced it'


@dataclass(frozen=True)
class Setup:
    """What start measures after authorization: declared source digests, pool slots and engine identity."""

    claims: tuple[str, ...]
    pool_slots: int
    engine: dict


def _summary(record: dict) -> dict:
    """What a start reports: the authorization anchor, whether setup completed and the prior hand-overs."""
    authorization = record['production']['authorization']
    return {'batchId': record['batchId'], 'authorizedAtEpoch': record['startEpoch'],
            'authorization': authorization['identity'], 'setup': authorization['setup'],
            'setupElapsed': authorization['setupElapsed'], 'priorAuthorizations': authorization['prior'],
            'priorAuthorizationsOmitted': authorization['priorOmitted']}


def _settings_refusal(batch_id: str, where: str) -> BudgetRefused:
    """A rerun whose approved content matches but whose AI settings differ never mints a new clock."""
    return BudgetRefused(f'A staged authorization of batch {batch_id} exists with other AI settings ({where}); rerun '
                         'with the same settings or discard it explicitly')


def authorize(root: Path, spec: BatchSpec) -> dict:
    """Start the clock now and make it durable, before any capacity inspection, hashing or queueing.

    The same authorization already published with pending setup, or left staged by an
    interrupted or refused start, is adopted with its original anchor; it never mints a new
    start. While another batch is active or draining the authorization is recorded staged
    (bounded) and the start is refused; running it again after that batch closes adopts it.
    """
    require_batch_id(spec.batch_id)
    if spec.claims:
        raise ValueError('Source digests are recorded by setup, after authorization')
    record = new_batch_record(spec, start_anchor())
    record['production']['authorization'].update(setup='pending', setupElapsed=None)
    resumed = _pending(root, record)
    if resumed is not None:
        return {**_summary(resumed), 'resumed': True, 'discardedStagings': []}
    with registry_lock(root):
        return _authorize_locked(root, record)


def _authorize_locked(root: Path, record: dict) -> dict:
    """Adopt, stage or publish under the registry lock; report every staging discarded on the way."""
    batch_id = record['batchId']
    discarded = sweep_stagings(root)
    match, replaced = _ours(root, record)
    refusal = _predecessor_current(root, batch_id)
    if refusal is not None:
        raise _refused_start(root, record, (match, replaced), refusal)
    discarded += [discard(root, row, 'replaced', REPLACED) for row in replaced]
    staged = _refresh_prior(root, batch_id, match.path) if match else stage_record(root, _with_prior(root, record))
    publish_staged(root, staged, batch_id)
    late = sweep_stagings(root)                         # other stagings of this id can never be adopted now
    if any(row['batchId'] == batch_id for row in late):
        _refresh_prior(root, batch_id, batch_directory(root, batch_id))
    return {**_summary(read_batch(root, batch_id)), 'resumed': match is not None,
            'discardedStagings': [{key: row[key] for key in ('name', 'cause', 'reason', 'miss')}
                                  for row in discarded + late]}


def _ours(root: Path, record: dict) -> tuple[Staging | None, list[Staging]]:
    """The staging this start adopts, and this batch id's other stagings a new hand-over replaces.

    Refuses by name while one of them cannot be dated, or when one matches the approved content but
    not the AI settings.
    """
    batch_id, identity = record['batchId'], record['production']['authorization']['identity']
    ours = [(row, assess(root, row)) for row in stagings(root) if row.batch_id == batch_id]
    undated = next(((row, state) for row, state in ours if state['state'] == UNPROVABLE), None)
    if undated:
        raise BudgetRefused(f'The staged start {undated[0].path.name} of batch {batch_id} cannot be dated '
                            f'({undated[1]["why"]}); it is left for the operator: correct the clock, or discard it '
                            'explicitly (discard_staged) and start again')
    adoptable = [row for row, state in ours if state['state'] == ADOPTABLE]
    match = next((row for row in adoptable if row.raw['production']['authorization']['identity'] == identity), None)
    if match is None and any(content_identity(row.raw) == content_identity(record) for row in adoptable):
        raise _settings_refusal(batch_id, 'staged, not yet started')
    return match, [row for row, state in ours if row is not match and state['state'] in (ADOPTABLE, FOREIGN)]


def _with_prior(root: Path, record: dict) -> dict:
    """The record with the earlier discarded authorizations of its batch id."""
    prior, omitted = prior_authorizations(root, record['batchId'])
    record['production']['authorization'].update(prior=prior, priorOmitted=omitted)
    return record


def _refresh_prior(root: Path, batch_id: str, directory: Path) -> Path:
    """Record in a staged or just-published record every earlier authorization of its id discarded since."""
    prior, omitted = prior_authorizations(root, batch_id)
    with locked_batch(root, batch_id, directory=directory) as session:
        record = session.read()
        block = record['production']['authorization']
        if (block['prior'], block['priorOmitted']) != (prior, omitted):
            block.update(prior=prior, priorOmitted=omitted)
            session.commit(record, {'event': 'prior-authorizations-recorded', 'omitted': omitted,
                                    'prior': [row['name'] for row in prior]})
    return directory


def _predecessor_current(root: Path, batch_id: str) -> PredecessorCurrent | None:
    """The refusal naming a still-current predecessor, or None when the batch may be published (others raise)."""
    try:
        refuse_creation(root, batch_id)
    except PredecessorCurrent as refusal:
        return refusal
    return None


def _refused_start(root: Path, record: dict, ours: tuple, refusal: PredecessorCurrent) -> PredecessorCurrent:
    """Keep the refused authorization staged (unless this batch id is taken) and say so."""
    batch_id, (match, replaced) = record['batchId'], ours
    if batch_directory(root, batch_id).exists() or archived_directory(root, batch_id).exists():
        return refusal                                   # this batch id is taken: never restarted, never staged
    if match:
        kept, note = match.raw, ''
    else:
        ended = [discard(root, row, 'replaced', REPLACED)['name'] for row in replaced if row.current]
        kept = _record_refused(root, record)
        note = f' It replaces the earlier hand-over {", ".join(ended)}, recorded as a miss.' if ended else ''
    return PredecessorCurrent(f'{refusal}. The authorization handed over at epoch {kept["startEpoch"]} is recorded; '
                              'running this start again after that batch closes adopts it as this batch\'s start '
                              f'while it still leaves room to deliver before its deadline.{note}')


def _record_refused(root: Path, record: dict) -> dict:
    """Stage a refused start's authorization: at most MAX_STAGED adoptable ones in all."""
    if len(adoptable_stagings(root)) >= MAX_STAGED:
        raise BudgetRefused(f'{MAX_STAGED} refused or interrupted starts are already recorded inside their delivery '
                            'deadlines; start or discard one first')
    stage_record(root, _with_prior(root, record))
    return record


def discard_staged(root: Path, name: str, reason: str) -> dict:
    """The operator's discard of one staged start, by its exact directory name, with a reason (a recorded miss)."""
    if type(name) is not str or STAGING.fullmatch(name) is None:
        raise ValueError('Name a staged start exactly (.creating-<batch>-<12 hex>)')
    if type(reason) is not str or not reason.strip():
        raise ValueError("Discarding a staged start records the operator's reason")
    with registry_lock(root):
        staging = staging_of(root / 'batches' / name)
        if staging is None:
            raise BudgetRefused(f'{name} is not a staged start under {root / "batches"}')
        return discard(root, staging, 'operator', f'operator: {reason.strip()}')


def _pending(root: Path, record: dict) -> dict | None:
    """The same authorization still waiting for setup, if this batch id holds one (live: never a new clock)."""
    batch_id = record['batchId']
    if not batch_directory(root, batch_id).is_dir():
        return None
    try:
        published = read_batch(root, batch_id)
    except BudgetAuthorityError:
        return None
    authorization = published['production']['authorization']
    if authorization['setup'] != 'pending':
        return None
    if authorization['identity'] == record['production']['authorization']['identity']:
        return published
    if content_identity(published) == content_identity(record):
        raise _settings_refusal(batch_id, 'published, its setup pending')
    return None


def _setup_problem(setup: Setup) -> str | None:
    """Declared source digests, pool slots and engine identity in the record's closed shapes."""
    claims = list(setup.claims)
    if len(claims) > BOUNDS['claims'] or claims != sorted(set(claims)) \
            or not all(type(item) is str and SHA256.fullmatch(item) for item in claims):
        return f'declared sources are at most {BOUNDS["claims"]} sorted unique SHA-256 digests'
    if type(setup.pool_slots) is not int or not 1 <= setup.pool_slots <= 16:
        return 'pool slots are an integer from 1 to 16'
    return None


def complete_setup(root: Path, batch_id: str, setup: Setup) -> dict:
    """Record setup under the running clock; the start anchor is never touched. Identical repeats are no-ops."""
    problem = _setup_problem(setup)
    if problem:
        raise ValueError(problem)
    with locked_batch(root, batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        if not _apply_setup(record, setup, elapsed):
            return {**_summary(record), 'committed': False}
        session.commit(record, {'event': 'batch-setup-completed', 'elapsed': elapsed, 'claims': list(setup.claims),
                                'poolSlots': setup.pool_slots, 'engine': setup.engine.get('identity')})
    return {**_summary(record), 'committed': True}


def _apply_setup(record: dict, setup: Setup, elapsed: float) -> bool:
    """Complete a pending setup in the record; False for an identical repeat, a refusal for anything else."""
    authorization = record['production']['authorization']
    values = (list(setup.claims), setup.pool_slots, setup.engine)
    if authorization['setup'] == 'complete':
        if (record['claims'], record['poolSlots'], record['engine']) != values:
            raise TaskConflict(f'Batch {record["batchId"]} completed its setup with other sources, slots or engine')
        return False
    if record['status'] != 'active':
        raise BudgetRefused(f'Batch {record["batchId"]} is {record["status"]}; its setup can no longer complete')
    record['claims'], record['poolSlots'], record['engine'] = values
    authorization.update(setup='complete', setupElapsed=elapsed)
    return True
