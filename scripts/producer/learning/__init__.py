"""Deterministic, next-run-only doctrine learning primitives."""

from learning.doctrine_lifecycle import (  # noqa: F401
    DoctrineCandidate,
    DoctrineFile,
    DoctrineLifecycleError,
    DoctrineLock,
    LessonProposal,
    build_candidate,
    capture_producer_run,
    capture_run,
    draft_proposal,
    promote_for_next_run,
    rollback_for_next_run,
    restore_lock,
    source_drift,
)
from learning.observations import (  # noqa: F401
    LearningObservation,
    critic_observation,
    manual_timeline_observation,
    qc_observation,
)
