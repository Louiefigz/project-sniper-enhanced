"""Bounded observation-only timings of existing Python render seams."""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager

_SEAMS = {
    ("headless.container_io", "create_snapshot"): "sealInput",
    ("graphics.graphics_render", "_sealed_hash"): "sealedCacheIdentity",
    ("headless.container_renderer", "render_to"): "containerTotal",
    ("headless.container_renderer", "_run"): "containerLaunch",
    ("headless.container_policy", "wait_and_copy"): "renderWaitAndCopy",
    ("headless.container_policy", "attest_image"): "imageAttestation",
    ("headless.network_probe", "probe_container"): "networkAttestation",
    ("headless.container_policy", "remove_container"): "containerRemoval",
    ("headless.container_policy", "reconcile_launch_abort"): "abortReconciliation",
    ("graphics.asset_proof", "prove_rendered_asset"): "hostMediaProof",
    ("graphics.comp_catalog_probe", "_measure_artifact"): "capabilityMeasurement",
}


@contextmanager
def phase_timings(rows: list):
    """Time calls/returns without replacing functions, arguments, or results.

    Spans are inclusive and may overlap; their sum is not elapsed work time.
    No argument values, locals, model inputs, or media bytes are collected.
    """
    if sys.getprofile() is not None:
        raise RuntimeError("capability profiler cannot replace an existing profiler")
    started = {}

    def observe(frame, event, _argument):
        label = _SEAMS.get((frame.f_globals.get("__name__"), frame.f_code.co_name))
        if label is None:
            return
        if event == "call":
            started[id(frame)] = (label, time.monotonic())
        if event == "return" and id(frame) in started:
            name, before = started.pop(id(frame))
            if len(rows) < 256:
                rows.append({"phase": name, "elapsedMs": round((time.monotonic() - before) * 1000)})

    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(None)
