"""Shared deterministic-gate runner for the Claude Code PRODUCER hooks.

Given an ``edit_plan.json`` inside a PRODUCER job (``<job>/producer/edit_plan.json``
with a manifest under ``<job>/source/``), run the controller-owned pre-render
gates and report failures. Mirrors the authoritative bundle in
``src/app/api/producer/auto-edit/planning-gates.ts`` — same scripts, same args.

Verdict handling has three outcomes so callers can choose policy:
- gate returns ``{"ok": false}``   -> FAILURE (a real plan defect; block)
- gate crashes/times out/non-JSON  -> INFRA (can't verify — the plan-write hook
  warns and continues; the render hook fails CLOSED before the irreversible step)
- gate returns ``{"ok": true}``    -> pass

Gates needing GUI-runtime artifacts (``template_usage`` digest, cut-approval
receipt, reference profile) are reported skipped. ``transcript_cut`` runs
(receipt-less base stage, NOT ``--previsual``) whenever the plan has a cutTrack,
mirroring the canonical bundle's unconditional call.
"""
import json
import os
import subprocess
import sys
import time

MAX_ERRORS_SHOWN = 12
GATE_TIMEOUT_S = 60          # per gate; the 150s total budget is the real cap
TOTAL_BUDGET_S = 150         # under the 180s hook timeout so the hook is never killed
_INTENT_KEYS = ("mode", "scope", "lanes", "excerpt", "brief", "pace",
                "style", "reference", "music", "audioEnhance")


def interpreter(repo):
    venv = os.path.join(repo, ".venv", "bin", "python3")
    return venv if os.path.isfile(venv) else (sys.executable or "python3")


def find_manifest(src):
    """The job's source manifest — canonical name first, then any ``*.json`` in
    ``<job>/source/`` that parses as a manifest (a ``sources`` array). Real jobs
    name it ``asset_manifest.json`` OR ``manifest.json``/``manifest_2min.json``."""
    if not os.path.isdir(src):
        return None
    for name in ("asset_manifest.json", "manifest.json"):
        path = os.path.join(src, name)
        if os.path.isfile(path):
            return path
    for name in sorted(f for f in os.listdir(src) if f.endswith(".json")):
        path = os.path.join(src, name)
        try:
            if isinstance(json.load(open(path)).get("sources"), list):
                return path
        except Exception:
            continue
    return None


def job_paths(plan_path):
    """(<job>, <src>, <manifest>) for a ``<job>/producer/plan`` path, or None
    when the file isn't a gate-able PRODUCER plan (no manifest under <job>/source)."""
    job = os.path.dirname(os.path.dirname(plan_path))
    src = os.path.join(job, "source")
    manifest = find_manifest(src)
    return (job, src, manifest) if manifest else None


def _load_plan(plan_path):
    try:
        return json.load(open(plan_path))
    except Exception:
        return None


def _operator_intent_json(job):
    """The operator_intent ``--expected-json`` from project.json, or None when
    there is no usable stamped intent. operator_intent_contract mandates only
    mode∈{short,longform} + a present scope (lanes defaults to {})."""
    pj = os.path.join(job, "project.json")
    if not os.path.isfile(pj):
        return None
    try:
        data = json.load(open(pj))
    except Exception:
        return None
    intent = data.get("resolvedIntent") or data.get("intent") or {}
    expected = {k: intent[k] for k in _INTENT_KEYS if k in intent}
    return json.dumps(expected) if expected.get("mode") in ("short", "longform") and "scope" in expected else None


def _gate_commands(plan_path, plan, src, manifest, job):
    cmds = [
        ("plan_lint", ["plan_lint.py", plan_path, manifest, src]),
        ("hook_contract", ["hook_contract.py", plan_path, src, manifest]),
        ("claims_contract", ["claims_contract.py", plan_path, src, manifest]),
    ]
    skipped = []
    intent = _operator_intent_json(job)
    if intent is not None:
        cmds.insert(0, ("operator_intent",
                        ["operator_intent_contract.py", plan_path, "--expected-json", intent]))
    else:
        skipped.append(("operator_intent", "no complete stamped intent in <job>/project.json"))
    # Mirror the canonical bundle: run transcript_cut whenever there is a cutTrack;
    # transcript_cut_contract self-skips only on an empty cutTrack.
    if (plan or {}).get("cutTrack"):
        cmds.append(("transcript_cut", ["transcript_cut_contract.py", plan_path, src, manifest]))
    else:
        skipped.append(("transcript_cut", "plan has no cutTrack"))
    skipped.append(("template_usage", "needs the GUI template-usage ledger + digest"))
    skipped.append(("reference_lint", "runs only when a reference profile is set"))
    return cmds, skipped


def _run(py, repo, argv, deadline):
    """One gate -> (status, errors), status in {"pass", "fail", "infra"}."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "infra", ["gate time budget exhausted before it could run"]
    script = os.path.join(repo, "scripts", "producer", argv[0])
    try:
        proc = subprocess.run([py, script, *argv[1:]], capture_output=True,
                              text=True, cwd=repo, timeout=min(GATE_TIMEOUT_S, remaining))
    except subprocess.TimeoutExpired:
        return "infra", [f"gate timed out (> {GATE_TIMEOUT_S}s)"]
    except Exception as exc:
        return "infra", [f"gate could not run ({exc})"]
    try:
        verdict = json.loads(proc.stdout.strip())
    except Exception:
        return "infra", [f"gate produced no JSON verdict (exit {proc.returncode}): "
                         f"{(proc.stdout or proc.stderr or '').strip()[-200:]}"]
    if not isinstance(verdict, dict):
        return "infra", [f"gate emitted non-object JSON verdict: {str(verdict)[:120]}"]
    if verdict.get("ok") and proc.returncode == 0:
        return "pass", []
    errors = list(verdict.get("errors", [])) or [f"gate reported failure (exit {proc.returncode})"]
    return "fail", errors


def evaluate_plan(plan_path, repo):
    """(failures, infra, skipped), or None if not a gate-able PRODUCER plan."""
    paths = job_paths(plan_path)
    if paths is None:
        return None
    job, src, manifest = paths
    plan = _load_plan(plan_path)
    py = interpreter(repo)
    cmds, skipped = _gate_commands(plan_path, plan, src, manifest, job)
    deadline = time.monotonic() + TOTAL_BUDGET_S
    failures, infra = [], []
    for gate, argv in cmds:
        status, errors = _run(py, repo, argv, deadline)
        if status == "fail":
            failures.append((gate, errors))
        elif status == "infra":
            infra.append((gate, errors))
    return failures, infra, skipped


def format_block(failures, infra, skipped, header):
    out = [header, ""]
    for gate, errors in failures:
        out.append(f"### {gate} — {len(errors)} error(s)")
        out += [f"  - {e}" for e in errors[:MAX_ERRORS_SHOWN]]
        if len(errors) > MAX_ERRORS_SHOWN:
            out.append(f"  … and {len(errors) - MAX_ERRORS_SHOWN} more (fix these first, re-run)")
        out.append("")
    for gate, errors in infra:
        out.append(f"[gate:{gate}] COULD NOT VERIFY — {errors[0] if errors else 'infra error'}")
    if skipped:
        out.append("gates not run here (interactive mode): "
                   + "; ".join(f"{g} — {r}" for g, r in skipped))
    return "\n".join(out)
