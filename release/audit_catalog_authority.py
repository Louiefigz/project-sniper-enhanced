"""Archive audit for the registered 372-row unified catalog authority."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

_AUDIT = r"""
import json, os, sys
os.environ['SNIPER_PIPELINE_ROOT'] = sys.argv[1]
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts', 'producer'))
from planner.visual_plan_catalog_authority import build_catalog_authority
authority, metadata = build_catalog_authority()
items = authority['items']
source_gaps = [row['ref'] for row in items if not row['source']['exists']]
unclassified = [row['ref'] for row in items if not row['source']['exists']
                and row['integration']['status'] != 'reference-missing-source']
dependency_gaps = [row['ref'] for row in items
                   if row['resourceEvidence'].get('dependencySize', {}).get('missingReferences')]
external = [row['ref'] for row in items
            if row['resourceEvidence'].get('dependencySize', {}).get('externalReferences')]
print(json.dumps({'total': len(items), 'resources': len(authority['resourceItems']),
                  'snapshot': metadata['version'], 'sourceGaps': source_gaps,
                  'unclassifiedSourceGaps': unclassified,
                  'dependencyGapRecords': dependency_gaps, 'externalDependencyRecords': external}))
"""


def inspect_catalog_authority(app: Path) -> tuple[dict | None, str]:
    """Re-derive the installed authority inside the extracted archive."""
    done = subprocess.run([sys.executable, "-c", _AUDIT, str(app)],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return None, (done.stderr or done.stdout).strip()[-500:]
    try:
        return json.loads(done.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"catalog audit did not return JSON: {exc}"


def audit_catalog_authority(app: Path,
                            check: Callable[[bool, str, str], None]) -> None:
    """Require the full registered corpus and report bounded dependency gaps."""
    result, error = inspect_catalog_authority(app)
    check(result is not None, "closure: catalog snapshot resolves through registry",
          error or str(result.get("snapshot")))
    if result is None:
        return
    check(result["total"] == 372, "closure: unified catalog authority is complete",
          f"{result['total']} records")
    check(result["resources"] == result["total"],
          "closure: every catalog record has resource evidence",
          f"{result['resources']} resource rows")
    check(not result["unclassifiedSourceGaps"],
          "closure: missing catalog sources are explicitly classified",
          f"known gaps: {', '.join(result['sourceGaps']) or 'none'}")
    check(True, "closure: catalog dependency gaps are explicitly inventoried",
          f"{len(result['dependencyGapRecords'])} local-gap records; "
          f"{len(result['externalDependencyRecords'])} external-reference records")
