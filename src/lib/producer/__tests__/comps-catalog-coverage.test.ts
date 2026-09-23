import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { COMPS_CATALOG } from "../comps-catalog";

const COMPOSITIONS = path.join(
  process.cwd(), "templates", "motion", "compositions",
);

function renderableTemplates(): string[] {
  return readdirSync(COMPOSITIONS)
    .filter((file) => file.endsWith(".html") && !file.startsWith("_gs-"))
    .map((file) => file.slice(0, -".html".length))
    .sort();
}

test("every renderable composition is visible to the editor brain", () => {
  const catalogKinds = new Set(COMPS_CATALOG.map((entry) => entry.kind));
  const hidden = renderableTemplates().filter((kind) => !catalogKinds.has(kind));
  assert.deepEqual(hidden, [],
    `Templates hidden from COMPS_CATALOG: ${hidden.join(", ")}`);
});

test("the planner-facing catalog has unique kinds backed by real templates", () => {
  const kinds = COMPS_CATALOG.map((entry) => entry.kind);
  assert.equal(new Set(kinds).size, kinds.length, "catalog kinds must be unique");
  for (const kind of kinds) {
    assert.doesNotThrow(() => readFileSync(
      path.join(COMPOSITIONS, `${kind}.html`), "utf8",
    ), `${kind} must resolve to a real composition template`);
  }
});

test("every editor default spec satisfies the renderer template contract", () => {
  const plan = {
    graphicsTrack: COMPS_CATALOG.map((entry, index) => ({
      kind: entry.kind,
      spec: entry.defaultSpec,
      // Editor samples must clear the longest registered completion floor
      // (avatar credibility = 5s; module modular cards = 4s).
      outStart: index * 7,
      outEnd: index * 7 + 6,
    })),
  };
  const result = spawnSync(
    path.join(process.cwd(), ".venv", "bin", "python3"),
    [path.join(process.cwd(), "scripts", "producer", "graphics", "template_contract_cli.py"), "--plan", "-"],
    { input: JSON.stringify(plan), encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stdout || result.stderr);
  const verdict = JSON.parse(result.stdout) as { ok?: boolean; errors?: unknown[] };
  assert.equal(verdict.ok, true, JSON.stringify(verdict.errors));
});
