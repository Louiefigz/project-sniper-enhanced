"""Combined retained fire/sparkles copy-repair and timing-reuse cohort."""
from __future__ import annotations

from pathlib import Path

from tests.p4_exit_scene_copy import run_copy_repair
from tests.p4_exit_scene_support import create_context
from tests.p4_exit_scene_timing import run_timing_move


def run_scene_cases(root: Path) -> dict:
    """Run both incremental claims against one governed bundle/cache."""
    context = create_context(root)
    copy_case, changed_scene, forced = run_copy_repair(context)
    timing_case = run_timing_move(context, changed_scene, forced)
    return {"copyRepair": copy_case, "timingMove": timing_case}
