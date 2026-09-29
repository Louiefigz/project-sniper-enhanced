"""Durable production tasks kept inside the per-batch budget authority (no second store).

Packaging only. The vocabulary and closed row schema are in ``task_schema``; task
definitions and enqueue checks in ``tasks``; dependency outcomes in ``dependencies``;
claims and enrolment in ``claims``; execution outcomes in ``callbacks``; run shutdown
(draining/close/archive) in ``lifecycle``; recovery in ``reconcile``; the typed host
capability/event contract in ``host_contract`` with the observed gate verdicts in
``host_verdicts``; and the locked Python API the coordinator commands call in ``api``.
Output formats (schema 5): format identity and policy in ``formats``, the output
authorization event in ``outputs``, Long lineage identity in ``lineage`` and the mixed
admission forecast in ``mixed_forecast``.
"""
