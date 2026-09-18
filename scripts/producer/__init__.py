"""PRODUCER — deterministic render pipeline for social-ready shorts + long-form cuts.

The brain (Claude skill or API route) authors ``edit_plan.json``; this package
validates it (``plan_lint``), compiles it (``compile_timeline``), and renders it
(``cut_speed`` → ``reframe`` → ``captions`` → ``master``). It never makes
creative decisions. See docs/producer/PRODUCER_PLAN.md.
"""
