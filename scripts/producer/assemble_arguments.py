"""Ordinary assembler arguments and the existing source/document admission gate.

This preserves the one CLI's defaults and authority checks. An explicit audio
policy selects implementation capability, never delivery or human approval.
"""
from __future__ import annotations

import argparse
import json
import os


def parse_arguments() -> argparse.Namespace:
    """Parse the established CLI, retaining legacy audio as the default."""
    parser = argparse.ArgumentParser(description="PRODUCER incremental-graphics assemble")
    parser.add_argument("base", help="the mastered graphics-free base (render.py --skip-graphics)")
    parser.add_argument("plan_path")
    parser.add_argument("out")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--fingerprint", default=None,
                        help="base receipt (default: base.fingerprint.json beside BASE)")
    parser.add_argument("--auto-base", action="store_true",
                        help="rebuild a missing/stale base; audio-only edits rebuild its audio bus")
    parser.add_argument("--manifest", default=None,
                        help="manifest for base rebuilds, source authority and music asset resolution")
    parser.add_argument("--audio-clock-policy", choices=("legacy-v1", "source-float-v2"),
                        default="legacy-v1")
    parser.add_argument("--source-bus-receipt-hash",
                        help="separately held render/graph source execution receipt")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--require-source-set-admission", action="store_true",
                        help="explicitly require sandbox source authority (the default)")
    policy.add_argument("--allow-legacy-unadmitted", action="store_true",
                        help="non-production migration only: accept a legacy manifest")
    args = parser.parse_args()
    if args.fingerprint is None:
        args.fingerprint = os.path.join(os.path.dirname(os.path.abspath(args.base)), "base.fingerprint.json")
    if not args.allow_legacy_unadmitted:
        os.environ["SNIPER_REQUIRE_SOURCE_SET_ADMISSION"] = "1"
    return args


def load_documents(args: argparse.Namespace) -> tuple[dict, str | None]:
    """Validate the canonical input and its existing execution/template authority."""
    from guided_presenter_base import require_unowned_presenter_absent
    from assemble import (delivery_authority_dir, require_template_usage_approval,
                          template_approval_required, validate_render_documents,
                          verify_execution_media_authority)
    with open(args.plan_path) as handle:
        plan = json.load(handle)
    require_unowned_presenter_absent(plan)
    manifest = args.manifest
    if not manifest and args.fingerprint and os.path.exists(args.fingerprint):
        with open(args.fingerprint) as handle:
            manifest = json.load(handle).get("manifestPath")
    if not args.allow_legacy_unadmitted and not manifest:
        raise RuntimeError("mandatory source-set admission requires a resolved manifest")
    if manifest:
        with open(manifest) as handle:
            document = json.load(handle)
        validate_render_documents(plan, document)
        verify_execution_media_authority(plan, document, manifest)
        require_template_usage_approval(args.plan_path, manifest,
            delivery_authority_dir(args.plan_path), os.path.dirname(os.path.abspath(manifest)))
    elif template_approval_required(delivery_authority_dir(args.plan_path)):
        raise RuntimeError("produced/full assemble requires --manifest to verify template history")
    else:
        validate_render_documents(plan)
    return plan, manifest


def default_cache_directory() -> str:
    """Return the existing shared graphics cache, not a new audio cache location."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "templates", "motion", "renders", "cache")
