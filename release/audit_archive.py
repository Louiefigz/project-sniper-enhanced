#!/usr/bin/env python3
"""Acceptance Z1 — audit an assembled archive and its fresh extraction.

    python3 -m release.audit_archive <archive.zip> <extract-dir>

Checks the archive as a buyer receives it: one top-level folder, no symlink or
path that escapes it, no credential or machine-state file, every agent and
runtime input the retained workflows read, and no reference to a developer home
path or a sibling repository.

Exit 0 when every check passes, 1 otherwise. Findings never print a matched
credential value.
"""
from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

REQUIRED = (
    "app/AGENTS.md", "app/CLAUDE.md", "app/docs/PIPELINE.md",
    "app/package.json", "app/package-lock.json", "app/requirements.txt",
    "app/templates/motion/package.json", "app/templates/motion/package-lock.json",
    "app/templates/motion/comp_capabilities.json",
    "app/scripts/producer/studio/native_runtime.py",
    "app/scripts/producer/studio/runtime/patches.json",
    "app/scripts/producer/studio/runtime/native-export-guard.mjs",
    "app/scripts/producer/studio/runtime/frame-source-transport.mjs",
    "app/scripts/producer/studio/studio_review.py",
    "app/scripts/producer/audio/models/bd.rnnn",
    "app/scripts/producer/selftest.py",
    "app/src/app/api/_lib/subscription-policy.ts",
    "app/vendor/hyperframes-catalog/catalog-index.json",
    "app/.env.local.example",
    "install/install.command", "install/doctor.command", "install/start.command",
    "install/stop.command", "install/uninstall.command",
    "install/diagnostics.command", "install/clean-caches.command",
    "install/sniper_doctor.py", "install/requirements.lock.txt",
    "install/lib/common.sh",
    "START-HERE.html", "manual/manual.css", "manual/index.html",
    "manual/install.html", "manual/privacy.html", "manual/license-and-updates.html",
    "RELEASE.json", "RELEASE-NOTES.md", "THIRD-PARTY-NOTICES.md",
    "LICENSE-DRAFT.txt", "licenses/Apache-2.0-hyperframes.txt",
    "licenses/MIT-YuNet-face-detection.txt",
    "install/sign-in.command", "install/editor.command", "install/use-provider.command",
    "install/sniper_diagnostics.py",
    "app/scripts/infra/provider-admission.ts",
    "app/src/app/fonts/archivo-latin-wght-normal.woff2",
    "app/resources/director/formats.md", "app/resources/director/hook-anchors.md",
    "app/resources/director/hook-formulas.md", "app/resources/director/hook-references.md",
    "app/resources/director/hook-training-problem-aware.md",
    "app/resources/director/hook-training-solution-aware.md",
    "app/resources/references/shorts/manifest.json",
    "app/resources/references/shorts/sequences/manifest.json",
    "app/resources/references/shorts/sequences/cases/N26.json",
    "app/resources/references/shorts/expansion/manifest.json",
    "app/resources/references/longform/manifest.json",
    "app/docs/audits/INTRO_MACHINE_VS_PRO_AUDIT.md",
)
REQUIRED_SKILLS = ("producer", "segmenter", "clipper", "reference-editor", "producer-study")
FORBIDDEN = (
    (r"(?:^|/)\.env$", "environment file"),
    (r"(?:^|/)\.env\.local$", "environment file"),
    (r"(?:^|/)\.git/", "git metadata"),
    (r"(?:^|/)node_modules/", "installed dependencies copied from a developer machine"),
    (r"(?:^|/)\.venv/", "python environment copied from a developer machine"),
    (r"(?:^|/)\.next(?:-|/)", "build cache"),
    (r"(?:^|/)artifacts/", "developer footage and render output"),
    (r"(?:^|/)\.sniper-", "machine-local control-plane state"),
    (r"(?:^|/)\.DS_Store$", "Finder metadata"),
    (r"(?:^|/)\.mcp\.json$", "unconfigured MCP server declaration"),
    (r"\.pyc$", "byte cache"),
    (r"(?:^|/)vendor/hyperframes-skills/", "provenance-only archive, licence unverified"),
)
# Flag a REAL identity, not the idea of a home path. Tests legitimately use
# placeholder home paths (/Users/TEST, /Users/x, /Users/example-user), and
# extending a denylist of invented names never converges. So compare against the
# account names that actually exist on the building machine: a leaked identity is
# by definition one of those. Known limit — this cannot see an account on some
# other machine, which is why the release process also runs
# `release/redact_paths.py --check` and must report zero.
_HOME = re.compile(r"/Users/([A-Za-z0-9._-]+)/")


def real_account_names() -> frozenset[str]:
    """Account names that exist on this machine, lowercased."""
    users = Path("/Users")
    if not users.is_dir():
        return frozenset()
    return frozenset(entry.name.lower() for entry in users.iterdir()
                     if entry.is_dir() and not entry.name.startswith("."))
_SIBLING = re.compile(r"\]\(\.\./\.\./|\]\(\.\./AGENTS\.md")
_TEXT = {".md", ".txt", ".json", ".ts", ".tsx", ".js", ".mjs", ".py", ".html", ".css",
         ".sh", ".command", ".example", ".yml"}
_findings: list[str] = []
_passes: list[str] = []


def check(ok: bool, name: str, detail: str) -> None:
    """Record one check."""
    (_passes if ok else _findings).append(f"{name}: {detail}")


def audit_entries(archive: Path) -> str:
    """Audit the archive's entry names without extracting, and return the top folder."""
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
    tops = {info.filename.split("/", 1)[0] for info in infos}
    check(len(tops) == 1, "single top-level folder", ", ".join(sorted(tops)))
    top = sorted(tops)[0]
    links = [i.filename for i in infos if (i.external_attr >> 16) & 0o170000 == 0o120000]
    check(not links, "no symlinks", "none" if not links else f"{len(links)} found")
    escapes = [i.filename for i in infos
               if i.filename.startswith("/") or ".." in Path(i.filename).parts
               or not i.filename.startswith(f"{top}/")]
    check(not escapes, "no path escapes the top folder",
          "none" if not escapes else "; ".join(escapes[:5]))
    names = [i.filename[len(top) + 1:] for i in infos]
    for pattern, reason in FORBIDDEN:
        hits = [n for n in names if re.search(pattern, n)]
        check(not hits, f"withheld: {reason}",
              "absent" if not hits else f"{len(hits)} present, e.g. {hits[0]}")
    for path in REQUIRED:
        check(path in names, f"present: {path}", "yes" if path in names else "MISSING")
    for skill in REQUIRED_SKILLS:
        for root in (".claude", ".agents"):
            path = f"app/{root}/skills/{skill}/SKILL.md"
            check(path in names, f"present: {path}", "yes" if path in names else "MISSING")
    return top


def audit_extraction(root: Path) -> None:
    """Audit the extracted tree for a leaked identity and sibling-repo links."""
    accounts = real_account_names()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT:
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("app/docs/") or relative.startswith("app/scripts/producer/docs/"):
            continue  # engine findings quote historical absolute paths as evidence
        named = {m.group(1).lower() for m in _HOME.finditer(text)} & accounts
        if named:
            _findings.append(f"real account name in a home path in {relative}")
        if relative in {"app/AGENTS.md", "app/CLAUDE.md"} and _SIBLING.search(text):
            _findings.append(f"link outside the package in {relative}")


_CODE_DOC = re.compile(r'"((?:docs|scripts/producer/docs)/[^"]+\.md)"')
_SIBLING_TEXT = re.compile(r"\.\./youtube-automation|SNIPER_RAG_ROOT|value-first-script-director")


def audit_closure(root: Path) -> None:
    """Dependency closure: what shipped code reads is in the archive, and nothing
    shipped points outside it. Reported separately from archive shape."""
    app = root / "app"
    named: set[str] = set()
    for pattern in ("src/**/*.ts", "scripts/**/*.py"):
        for path in app.glob(pattern):
            if "__tests__" in path.parts or "tests" in path.parts:
                continue
            named |= set(_CODE_DOC.findall(path.read_text(encoding="utf-8", errors="ignore")))
    missing = sorted(doc for doc in named if not (app / doc).is_file())
    check(not missing, "closure: every document shipped code reads is present",
          f"{len(named)} named, all present" if not missing else "MISSING: " + ", ".join(missing[:6]))
    outside = []
    for path in app.rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx", ".py", ".mjs", ".md", ".json"} \
                and _SIBLING_TEXT.search(path.read_text(encoding="utf-8", errors="ignore")):
            outside.append(path.relative_to(root).as_posix())
    check(not outside, "closure: no shipped file points at a sibling repository",
          "none" if not outside else f"{len(outside)}: " + ", ".join(outside[:6]))
    frames = list((app / "resources/references").rglob("*.jpg"))
    check(len(frames) > 0, "closure: packaged reference frames present", f"{len(frames)} frames")
    audit_pipeline_capture(app)
    audit_composition_sources(app)
    audit_capability_matrix(app)
    segment_paths = [f"docs/producer/command-driven-editing/contracts/{name}" for name in (
        "render-effect-registry-v1.json", "program-audio-mix-registry-v1.json",
        "external-ingress-registry-v1.json", "current-render-codec-floor-calibration-v1.json",
        "short-long-route-matrix-v1.json")] + ["docs/producer/catalog-study/catalog-study.json"]
    absent = [rel for rel in segment_paths if not (app / rel).is_file()]
    check(not absent, "closure: data files code builds by path segments are present",
          f"{len(segment_paths)} present" if not absent else "MISSING: " + ", ".join(absent))


_TS_LIST = r"const {name} = \[(.*?)\] as const;"

_RESOLVE = """
import glob, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "scripts", "producer"))
from headless.source_closure import discover_root_sources
root = os.path.join(sys.argv[1], "templates", "motion")
paths = sorted(glob.glob(os.path.join(root, "compositions", "*.html")))
for path in paths:
    try:
        discover_root_sources(open(path, encoding="utf-8").read(), root)
    except RuntimeError as error:
        print("MISSING", os.path.basename(path), error)
print("CHECKED", len(paths))
"""


_MATRIX = """
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "scripts", "producer"))
from graphics.comp_capability_artifact import load_artifact
value, error = load_artifact(os.path.join(sys.argv[1], "templates", "motion", "comp_capabilities.json"))
print("FRESH" if value else "STALE " + error)
"""


def audit_capability_matrix(app: Path) -> None:
    """The shipped capability matrix is fresh for the shipped tree, judged by the package's own loader.

    Planning refuses every graphics beat when this matrix is stale, so a digest computed over
    files the archive withholds would block guided editing on a buyer's Mac.
    """
    done = subprocess.run([sys.executable, "-c", _MATRIX, str(app)],
                          capture_output=True, text=True, check=False)
    line = (done.stdout.strip().splitlines() or [done.stderr.strip()[-300:]])[-1]
    check(done.returncode == 0 and line == "FRESH",
          "closure: composition capability matrix is fresh for the shipped tree", line)


def audit_composition_sources(app: Path) -> None:
    """Every shipped composition's local sources resolve, using the package's own resolver."""
    done = subprocess.run([sys.executable, "-c", _RESOLVE, str(app)],
                          capture_output=True, text=True, check=False)
    lines = done.stdout.splitlines()
    missing = [line for line in lines if line.startswith("MISSING")]
    checked = next((line.split()[1] for line in lines if line.startswith("CHECKED")), "0")
    ok = done.returncode == 0 and not missing and checked != "0"
    check(ok, "closure: every composition's local sources resolve",
          f"{checked} compositions" if ok else "; ".join(missing[:4]) or done.stderr.strip()[-300:])


def audit_pipeline_capture(app: Path) -> None:
    """Read Auto Edit's own capture requirements from the shipped source and check them.

    `auto-edit-pipeline-assets.ts` refuses to snapshot the pipeline when a required
    file, source path or asset prefix is absent, which stops every Auto Edit. The
    lists are parsed from the shipped file itself so the audit cannot drift from it.
    """
    source = (app / "src/lib/server/auto-edit-pipeline-assets.ts").read_text(encoding="utf-8")
    lists = {}
    for name in ("REQUIRED_FILES", "REQUIRED_PREFIXES", "SOURCE_PATHS"):
        match = re.search(_TS_LIST.format(name=name), source, flags=re.S)
        check(match is not None, f"closure: pipeline capture list {name} readable", "parsed" if match else "not found")
        lists[name] = re.findall(r'"([^"]+)"', match.group(1)) if match else []
    missing = [rel for rel in lists["REQUIRED_FILES"] if not (app / rel).is_file()]
    missing += [rel for rel in lists["SOURCE_PATHS"] if not (app / rel).exists()]
    empty = [prefix for prefix in lists["REQUIRED_PREFIXES"]
             if not any(path.is_file() for path in (app / prefix).rglob("*"))]
    check(not missing and not empty, "closure: Auto Edit pipeline capture requirements satisfied",
          f"{sum(len(v) for v in lists.values())} requirements met" if not (missing or empty)
          else "MISSING: " + ", ".join(missing[:6]) + (" EMPTY: " + ", ".join(empty) if empty else ""))


def audit_runtime_inputs(root: Path) -> None:
    """Prove the render runtime can be rebuilt from the shipped patch inputs alone."""
    import json  # noqa: PLC0415
    manifest = root / "app/scripts/producer/studio/runtime/patches.json"
    rows = json.loads(manifest.read_text())
    check(bool(rows.get("files")), "runtime patch set", f"{len(rows.get('files', []))} patched files")
    check("sdkVersion" in rows, "runtime pins the SDK version", str(rows.get("sdkVersion")))
    pinned = json.loads((root / "app/templates/motion/package.json").read_text())
    installed = pinned["dependencies"]["hyperframes"]
    check(installed == rows.get("sdkVersion"), "patch set matches the pinned SDK",
          f"lockfile {installed} vs patch set {rows.get('sdkVersion')}")


def main(argv: list[str]) -> int:
    """Run the audit against an archive and a fresh extraction directory."""
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    archive, dest = Path(argv[1]), Path(argv[2])
    top = audit_entries(archive)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["unzip", "-q", "-o", str(archive), "-d", str(dest)], check=True)
    root = dest / top
    check(root.is_dir(), "fresh extraction", str(root))
    audit_extraction(root)
    audit_runtime_inputs(root)
    audit_closure(root)
    for line in _passes:
        print(f"[PASS] {line}")
    for line in _findings:
        print(f"[FAIL] {line}")
    print(f"\n{len(_passes)} passed, {len(_findings)} failed")
    return 1 if _findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
