// intent-presets assertions — run with: npx tsx src/lib/producer/__tests__/intent-presets.test.ts
// Guards the TS mirror of scripts/producer/edit_scope.py: the lane/scope/
// directive vocabulary is parsed OUT OF THE PYTHON FILE, so a rename there
// fails here instead of drifting silently.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  AUDIO_ENHANCE_PRESETS,
  DIRECTIVE_WORDS,
  INTENT_PRESETS,
  LANES,
  PACES,
  SCOPES,
  SCOPE_LANE_DEFAULTS,
  STYLES,
  deriveScopeAndLanes,
  intentBadge,
  presetToIntent,
  resolveLanes,
  validateIntent,
  type Lane,
} from "../intent-presets";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EDIT_SCOPE = readFileSync(
  path.join(HERE, "../../../../scripts/producer/edit_scope.py"),
  "utf-8",
);
const PRODUCER_CONFIG = readFileSync(
  path.join(HERE, "../../../../scripts/producer/producer_config.py"),
  "utf-8",
);

// 1) LANES verbatim (order + names) from `LANES = (...)`.
{
  const m = EDIT_SCOPE.match(/^LANES = \(([^)]*)\)/m);
  assert.ok(m, "edit_scope.py LANES tuple not found");
  const pyLanes = [...m![1].matchAll(/"(\w+)"/g)].map((x) => x[1]);
  assert.deepEqual([...LANES], pyLanes, "LANES must match edit_scope.py verbatim");
}

// 2) Scope ladder + per-scope lane activation from the SCOPES dict.
{
  const m = EDIT_SCOPE.match(/^SCOPES[^=]*= \{([\s\S]*?)^\}/m);
  assert.ok(m, "edit_scope.py SCOPES dict not found");
  const entries = [...m![1].matchAll(/"(\w+)":\s*dict\(([\s\S]*?)\)/g)];
  assert.deepEqual([...SCOPES], entries.map((e) => e[1]), "scope ladder must match");
  for (const [, scope, body] of entries) {
    const py: Record<string, boolean> = {};
    for (const [, lane, val] of body.matchAll(/(\w+)=(True|False)/g)) py[lane] = val === "True";
    assert.deepEqual(
      SCOPE_LANE_DEFAULTS[scope as keyof typeof SCOPE_LANE_DEFAULTS],
      py,
      `SCOPE_LANE_DEFAULTS.${scope} must match edit_scope.py`,
    );
  }
}

// 3) Directive words from `_DIRECTIVE_WORDS = frozenset({...})`.
{
  const m = EDIT_SCOPE.match(/_DIRECTIVE_WORDS = frozenset\(\{([^}]*)\}\)/);
  assert.ok(m, "edit_scope.py _DIRECTIVE_WORDS not found");
  const py = [...m![1].matchAll(/"(\w+)"/g)].map((x) => x[1]).sort();
  assert.deepEqual([...DIRECTIVE_WORDS].sort(), py, "directive words must match");
}

// 3b) Every pace (incl. every style) has its pacing_<pace> profile in
// producer_config.MODES["short"] — plan_lint_motion._pacing_profile maps
// target.pace -> pacing_<pace> (dashes -> underscores); a missing profile
// would silently fall back to the default fast floor.
{
  for (const pace of PACES) {
    const key = `"pacing_${pace.replace(/-/g, "_")}": {`;
    assert.ok(
      PRODUCER_CONFIG.includes(key),
      `producer_config.py must define ${key.slice(1, -3)} for pace "${pace}"`,
    );
  }
  // STYLES are a subset of PACES (a style preset picks its own tempo profile).
  for (const s of STYLES) {
    assert.ok((PACES as readonly string[]).includes(s), `style "${s}" missing from PACES`);
  }
}

// 4) resolveLanes semantics parity with edit_scope.resolve_lanes.
{
  // "auto" cannot activate a lane the scope excludes (light has no graphics).
  assert.equal(resolveLanes("light", { graphics: "auto" }).graphics, "off");
  // "off"/"operator" always beat the scope.
  assert.equal(resolveLanes("produced", { broll: "off" }).broll, "off");
  assert.equal(resolveLanes("produced", { graphics: "operator" }).graphics, "operator");
  // trim activates nothing.
  assert.deepEqual(
    Object.values(resolveLanes("trim")),
    LANES.map(() => "off"),
  );
}

// 5) Preset → target mapping against the edit_scope vocabulary.
{
  const activeSet = (scope: (typeof SCOPES)[number], lanes: Record<string, unknown>) =>
    LANES.filter((l) => resolveLanes(scope, lanes)[l] === "auto");

  const byId = Object.fromEntries(INTENT_PRESETS.map((p) => [p.id, p]));
  assert.deepEqual(
    Object.keys(byId).sort(),
    [
      "angela-involved",
      "caleb-light",
      "jadenly-produced",
      "light-short",
      "longform-produced",
      "produced-short",
      "trim-only",
    ],
  );

  assert.deepEqual(activeSet("light", byId["light-short"].lanes), ["motion", "captions"]);
  assert.equal(byId["light-short"].mode, "short");
  assert.equal(byId["light-short"].audioEnhance?.preset, "voice-rnn");

  assert.deepEqual(activeSet("produced", byId["produced-short"].lanes), [...LANES]);
  assert.equal(byId["produced-short"].mode, "short");

  assert.deepEqual(activeSet("produced", byId["longform-produced"].lanes), [...LANES]);
  assert.equal(byId["longform-produced"].mode, "longform");
  assert.equal(byId["longform-produced"].audioEnhance?.preset, "voice");

  assert.deepEqual(activeSet("trim", byId["trim-only"].lanes), []);
  assert.equal(byId["trim-only"].mode, null, "trim-only follows the Short|Long toggle");

  // STYLE presets — pace/style pair up; music remains operator-opt-in.
  // Caleb light: captions carry the reel; motion waived (CALEB_STYLE §3 Z1);
  // no bed (§6 M1); no dialogue cleanup (§6 M3: breath gaps stay).
  assert.deepEqual(activeSet("light", byId["caleb-light"].lanes), ["captions"]);
  assert.equal(byId["caleb-light"].pace, "caleb");
  assert.equal(byId["caleb-light"].style, "caleb");
  assert.equal(byId["caleb-light"].music, false);
  assert.equal(byId["caleb-light"].audioEnhance, undefined);
  // Jaden recommends a bed, but selecting the style must not enable one.
  assert.deepEqual(activeSet("produced", byId["jadenly-produced"].lanes),
    LANES.filter((lane) => lane !== "transitions"));
  assert.equal(byId["jadenly-produced"].pace, "jadenly");
  assert.equal(byId["jadenly-produced"].style, "jadenly");
  assert.equal(byId["jadenly-produced"].music, false);
  // Angela has the same explicit-checkbox safety contract.
  assert.equal(byId["angela-involved"].scope, "full");
  assert.deepEqual(activeSet("full", byId["angela-involved"].lanes),
    LANES.filter((lane) => lane !== "motion" && lane !== "transitions"));
  assert.equal(byId["angela-involved"].pace, "angela");
  assert.equal(byId["angela-involved"].style, "angela");
  assert.equal(byId["angela-involved"].music, false);
  for (const s of STYLES) {
    const p = INTENT_PRESETS.find((x) => x.style === s);
    assert.ok(p, `no preset carries style "${s}"`);
    assert.equal(p!.mode, "short", `${p!.id}: style grammars are shorts-measured only`);
    assert.equal(p!.pace, s, `${p!.id}: pace must name the pacing_${s} profile`);
  }

  for (const p of INTENT_PRESETS) {
    assert.notEqual(p.music, true, `${p.id}: presets must never opt into music`);
    assert.ok((SCOPES as readonly string[]).includes(p.scope), `${p.id}: unknown scope`);
    for (const lane of Object.keys(p.lanes)) {
      assert.ok((LANES as readonly string[]).includes(lane), `${p.id}: unknown lane ${lane}`);
    }
    if (p.audioEnhance) {
      assert.ok(
        (AUDIO_ENHANCE_PRESETS as readonly string[]).includes(p.audioEnhance.preset),
        `${p.id}: unknown audioEnhance preset`,
      );
    }
    assert.ok(p.will.length > 0 && p.wont.length > 0, `${p.id}: needs will/wont descriptions`);
    // Every preset validates as a stored intent for both toggle modes.
    validateIntent(presetToIntent(p, "short"));
    validateIntent(presetToIntent(p, "longform"));
  }

  // Choosing another preset replaces a prior explicit music choice instead of
  // carrying a stale bed into the new intent.
  const replacement = presetToIntent(byId["longform-produced"], "longform");
  assert.notEqual(replacement.music, true);
}

// 6) deriveScopeAndLanes round-trips every checkbox combination (2^6).
{
  for (let mask = 0; mask < 1 << LANES.length; mask++) {
    const active = {} as Record<Lane, boolean>;
    LANES.forEach((l, i) => (active[l] = Boolean(mask & (1 << i))));
    const { scope, lanes } = deriveScopeAndLanes(active);
    const resolved = resolveLanes(scope, lanes);
    for (const l of LANES) {
      assert.equal(
        resolved[l] === "auto",
        active[l],
        `mask ${mask}: lane ${l} should be ${active[l] ? "auto" : "off"} (scope ${scope})`,
      );
    }
  }
}

// 7) validateIntent fails loudly on garbage (no-fallback rule).
{
  const good = { mode: "short", scope: "light", lanes: { broll: "off" } };
  assert.deepEqual(validateIntent(good).lanes, { broll: "off" });
  assert.throws(() => validateIntent({ ...good, scope: "trm" }), /unknown scope/);
  assert.throws(() => validateIntent({ ...good, lanes: { zooms: "off" } }), /unknown lane/);
  assert.throws(() => validateIntent({ ...good, lanes: { broll: "yes" } }), /directive/);
  assert.throws(() => validateIntent({ ...good, lanes: { broll: ["b1"] } }), /asset lists/);
  assert.throws(() => validateIntent({ ...good, pace: "fast" }), /pace/);
  assert.throws(() => validateIntent({ ...good, style: "mrbeast" }), /style/);
  assert.deepEqual(validateIntent({ ...good, style: "caleb", pace: "caleb" }).style, "caleb");
  assert.throws(() => validateIntent({ ...good, audioEnhance: { preset: "loud" } }), /audioEnhance/);
  assert.throws(() => validateIntent({ ...good, music: "yes" }), /music/);
  assert.throws(() => validateIntent({ mode: "reel", scope: "light", lanes: {} }), /mode/);
}

// 8) Badge text.
{
  assert.equal(intentBadge({ mode: "short", scope: "light" }), "SHORT · Light");
  assert.equal(intentBadge({ mode: "longform", scope: "produced" }), "LONG · Produced");
}

console.log("intent-presets.test.ts: all assertions passed");
