"""Derive the release's Node floor from the actual dependency closures.

Every package in both lockfiles that npm installs on a Mac (its ``os``/``cpu``
fields admit darwin and arm64 or x64) contributes its ``engines.node`` range.
The floor is the lowest version >= 22.0.0 that satisfies every range, evaluated
with the ``semver`` package npm itself uses (from the release source's
``node_modules``). A range that semver cannot parse, an ``engines.node`` that is
not a string, or a set of ranges no Node >= 22 satisfies fails the build.

Also recorded: the majors in which no release satisfies every range (for
example 23, when one package accepts ``^22.13.0 || >=24``), which the installer
warns about but does not refuse.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from release.stage import StagingError

LOCKFILES = ("package-lock.json", "templates/motion/package-lock.json")
_BASELINE = "22.0.0"
_SCRIPT = r"""
const semver = require(process.argv[1]);
const fs = require("fs");
const baseline = process.argv[2];
const lockfiles = JSON.parse(process.argv[3]);
const admits = (list, want) => !Array.isArray(list) || list.length === 0
  || list.some((v) => want.includes(v)) || (list.every((v) => v.startsWith("!"))
  && !list.some((v) => want.includes(v.slice(1))));
const ranges = [], bad = [];
for (const file of lockfiles) {
  const lock = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const [name, entry] of Object.entries(lock.packages || {})) {
    if (!entry.engines || entry.engines.node === undefined) continue;
    if (!admits(entry.os, ["darwin"]) || !admits(entry.cpu, ["arm64", "x64"])) continue;
    const range = entry.engines.node;
    if (typeof range !== "string" || semver.validRange(range) === null) {
      bad.push(`${file}:${name}: ${JSON.stringify(range)}`); continue;
    }
    ranges.push({ where: `${file}:${name}`, range });
  }
}
const ok = (v) => ranges.every((r) => semver.satisfies(v, r.range));
const candidates = new Set([baseline]);
for (const r of ranges) for (const set of new semver.Range(r.range).set) {
  const low = semver.minVersion(set.map((c) => c.value).join(" ") || "*");
  if (low && semver.gte(low, baseline)) candidates.add(low.version);
}
const sorted = [...candidates].sort(semver.compare);
const floor = sorted.find(ok) || null;
const highest = Math.max(30, ...sorted.map((v) => semver.major(v) + 1));
const unsupported = [];
for (let major = semver.major(baseline); major <= highest; major += 1) {
  const probes = sorted.filter((v) => semver.major(v) === major).concat([`${major}.0.0`, `${major}.999.999`]);
  if (!probes.some(ok)) unsupported.push(major);
}
console.log(JSON.stringify({ floor, bad, evaluated: ranges.length, unsupported,
  binding: ranges.filter((r) => floor && !semver.satisfies(_BASELINE_, r.range)).map((r) => r.where) }));
""".replace("_BASELINE_", json.dumps(_BASELINE))


def node_requirements(root: Path, node: str = "node") -> dict[str, object]:
    """Floor, majors to warn about, and which packages set the floor.

    Args:
        root: Release source root with both lockfiles and ``node_modules/semver``.
        node: Node executable that evaluates the ranges.

    Raises:
        StagingError: semver is missing, a range cannot be evaluated, or no
            Node >= 22 satisfies every range.
    """
    root = root.resolve()
    semver = root / "node_modules/semver"
    if not (semver / "package.json").is_file():
        raise StagingError("node_modules/semver is missing; run npm ci in the release source first")
    files = [str(root / name) for name in LOCKFILES]
    done = subprocess.run([node, "-e", _SCRIPT, str(semver), _BASELINE, json.dumps(files)],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise StagingError(f"could not evaluate engines.node ranges: {done.stderr.strip()[-400:]}")
    result = json.loads(done.stdout)
    if result["bad"]:
        raise StagingError("engines.node ranges that cannot be evaluated: " + "; ".join(result["bad"][:5]))
    if not result["floor"]:
        raise StagingError("no Node >= 22.0.0 satisfies every engines.node range in the lockfiles")
    prefix = f"{root}/"
    return {"floor": result["floor"], "unsupported_majors": result["unsupported"],
            "ranges_evaluated": result["evaluated"],
            "set_by": sorted(where.replace(prefix, "", 1) for where in result["binding"])}
