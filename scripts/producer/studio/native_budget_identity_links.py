"""Declared identities linked to host transcript owners (P3b-11): exactly one owner, or unknown with a named reason.

A6u links usage by host handle only. A declared handle (``studio.production.declared_identity``) names its host
and Sniper session; this module finds the one transcript owner (A6u ``Unit.owner`` = host, thread, turn) whose
records are that execution's, always at thread level (``'*'``):
- a director: the ``hostThread`` it declared at enrolment (Claude Code session id, Codex thread id);
- a Claude Code subagent: its agent id, which A6u reads as a subagent transcript's thread (``agentId``);
- a Codex subagent: the one rollout ``agent_usage.collect_files`` reports (``threads``) as spawned from its session
  director's ``hostThread`` under its agent path. Zero or several such rollouts link nothing.

Host handles keep A6u's exact owner (``native_budget_usage.transcript_links`` falls back to the thread when no
turn-level record exists); process handles and tasks without a handle link nothing. The declared director rows
are passed in (``ai_usage`` reads them); this module never reads the record, and it never guesses: a declared
handle without one owner is unknown, never counted as zero.
"""
from __future__ import annotations

NO_HOST_THREAD = 'no host thread was declared at enrolment'
NO_ROLLOUT = 'no rollout names this agent path under the director thread'
SEVERAL_ROLLOUTS = '{count} rollouts name this agent path under the director thread'
DIRECTOR_ROWS = '{count} declared director rows name session {session}'
NO_TRANSCRIPT = 'a {kind} handle names no host transcript'
ANY_TURN = '*'


def _director_thread(handle: dict, directors: list[dict]) -> tuple[str | None, str | None]:
    """(the host thread of the one director row of the handle's session, None) or (None, the reason)."""
    rows = [row for row in directors if row['handle']['session'] == handle['session']]
    if len(rows) != 1:
        return None, DIRECTOR_ROWS.format(count=len(rows), session=handle['session'])
    thread = rows[0]['handle']['hostThread']
    return (thread, None) if thread is not None else (None, NO_HOST_THREAD)


def _claude_subagent(handle: dict, _directors: list[dict], _threads: dict) -> tuple[tuple | None, str | None]:
    """A Claude Code subagent's transcript is owned by its agent id (A6u reads ``agentId`` as the thread)."""
    return ('claude-code', handle['agent'], ANY_TURN), None


def _codex_subagent(handle: dict, directors: list[dict], threads: dict) -> tuple[tuple | None, str | None]:
    """The one rollout spawned from the session director's thread under this agent path, or the reason."""
    parent, reason = _director_thread(handle, directors)
    if parent is None:
        return None, reason
    found = [thread for thread, row in threads.items()
             if row['parent'] == parent and row['agentPath'] == handle['agent']]
    if len(found) == 1:
        return ('codex', found[0], ANY_TURN), None
    return None, SEVERAL_ROLLOUTS.format(count=len(found)) if found else NO_ROLLOUT


SUBAGENT_RULES = {'claude-code': _claude_subagent, 'codex': _codex_subagent}   # one per host_contract.HOSTS


def _resolve(handle: dict | None, directors: list[dict], threads: dict) -> tuple[tuple | None, str | None]:
    """(the transcript owner, None) or (None, why none)."""
    if handle is None or handle['type'] == 'process':
        return None, NO_TRANSCRIPT.format(kind='process' if handle else 'missing')
    if handle['type'] == 'host':
        return (handle['host'], handle['thread'], handle['turn']), None
    if handle['agent'] is not None:
        return SUBAGENT_RULES[handle['host']](handle, directors, threads)
    if handle['hostThread'] is None:
        return None, NO_HOST_THREAD
    return (handle['host'], handle['hostThread'], ANY_TURN), None


def link_key(handle: dict | None, directors: list[dict], threads: dict) -> tuple | None:
    """The transcript owner a task's usage is linked to.

    Args:
        handle: The task's handle (declared, host or process), or None.
        directors: The declared director rows (task rows whose handle is a declared director handle).
        threads: ``agent_usage.collect_files(...)['threads']``: thread id → ``{'parent', 'agentPath'}``.

    Returns:
        ``(host, thread, '*')`` for a declared handle with exactly one owner, the exact ``(host, thread, turn)``
        for a host handle, and None otherwise (``unlinked_reason`` says why).
    """
    return _resolve(handle, directors, threads)[0]


def unlinked_reason(handle: dict | None, directors: list[dict], threads: dict) -> str:
    """Why ``link_key`` returned None for this handle.

    Raises:
        ValueError: The handle is linked, so there is no reason to give.
    """
    key, reason = _resolve(handle, directors, threads)
    if key is not None:
        raise ValueError(f'the handle is linked to {key}; it has no unlinked reason')
    return reason


def task_links(tasks: list[dict], directors: list[dict], threads: dict) -> dict:
    """Every task id → its ``link_key`` (None: linked to nothing)."""
    return {task['id']: link_key(task['handle'], directors, threads) for task in tasks}


def unlinked_reasons(tasks: list[dict], directors: list[dict], threads: dict) -> list[str]:
    """Why the declared tasks that link nothing do not: each distinct reason once, in task order.

    How many tasks are affected is the caller's ``host task(s) have no transcript record`` count.
    """
    reasons: dict[str, None] = {}
    for task in tasks:
        handle = task['handle']
        if handle is None or handle['type'] != 'declared':
            continue
        key, reason = _resolve(handle, directors, threads)
        if key is None:
            reasons[reason] = None
    return list(reasons)
