"""The run's AI governance: what the director's declared host lets Sniper claim, and each claim's rules.

Recorded at director enrollment from the gate verdicts of the handle's host (``host_verdicts``).
The handle is self-declared: no host adapter verifies it. Only the mode and limitations are
kept for the run; tool cleanup is judged per task from each task's own handle host
(``task_schema.handle_cleans_up``), never from whichever director enrolled last.
"""
from __future__ import annotations

from studio.production.host_contract import CHILD_ENVIRONMENT, governance, parse_capabilities
from studio.production.host_verdicts import HOST_RECORDS, SOURCE
from studio.production.task_schema import is_ai

RULES = {'supervised': 'the coordinator must stay alive to interrupt this turn at its deadline and confirm its '
                       'termination; nothing expires it if the coordinator is gone',
         'unattended': 'the host expires this turn at its deadline',
         'record-only': 'nothing enforces this deadline; it is recorded and counted only'}


def host_governance(handle: dict) -> dict:
    """The run's governance mode and limitations from the director's declared host (record-only without one).

    The handle is self-declared: no host adapter verifies it (see HOST_CAPABILITY_GATE). Tool
    cleanup is never read from here; each task's own handle host decides it.
    """
    record = HOST_RECORDS.get(handle['host']) if handle['type'] == 'host' else None
    report = governance(parse_capabilities(record) if record else None)
    return {**{key: report[key] for key in ('host', 'version', 'mode', 'unsupported', 'unproven')},
            'source': SOURCE if record else 'no observed capability record for this host'}


def host_rules(record: dict, task: dict) -> dict | None:
    """For AI work: how its deadline can be enforced and the clean environment every host child needs."""
    if not is_ai(task):
        return None
    run = record['production']['governance'] or host_governance({'type': 'process'})
    return {'deadlineEnforcement': run['mode'], 'rule': RULES[run['mode']], 'cleanEnvironment': list(CHILD_ENVIRONMENT)}
