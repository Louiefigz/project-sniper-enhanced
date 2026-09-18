import assert from "node:assert/strict";
import { test } from "node:test";
import { parseShortDirection, shortDirectionInstructions, shortMediaPolicy, shortDirectionForStyle } from "../short-direction";
import { validateIntent } from "../intent-presets";
import { buildAutoEditRequest, buildStarterPlan } from "../intent-flow";
import { parseAutoEditIntent } from "../../../app/api/producer/auto-edit/stream";
import { gateBundleOperatorIntent } from "../../../app/api/producer/auto-edit/planning-gates";
import { assertIntentMatches } from "../../../app/api/producer/auto-edit/operator-intent-authority";
import type { AssetManifest } from "../types";

test("requested treatment survives stored intent, launch, plan target and gate authority", () => {
  const shortDirection = { selection: "requested", request: "Nate Herk — develop the same offer", supportingVideo: "source-first" };
  const intent = validateIntent({ mode: "short", scope: "produced", lanes: {}, shortDirection });
  const body = buildAutoEditRequest("/tmp/producer", intent);
  const parsed = parseAutoEditIntent(body)!;
  assert.deepEqual(parsed.shortDirection, shortDirection);
  assert.deepEqual(gateBundleOperatorIntent("produced", parsed).shortDirection, shortDirection);
  assert.deepEqual(buildStarterPlan({ sources: [] } as unknown as AssetManifest, intent).target.shortDirection, shortDirection);
  assert.throws(() => assertIntentMatches(intent, { ...intent, shortDirection: { selection: "auto", supportingVideo: "source-first" } }), /shortDirection/);
});

test("automatic selection carries the source-first and show-the-change obligations", () => {
  const auto = parseShortDirection({ selection: "auto", supportingVideo: "source-first" }, "short")!;
  const prompt = shortDirectionInstructions(auto);
  assert.match(prompt, /retained message/); assert.match(prompt, /outside the dialogue cut/);
  assert.match(prompt, /visible operation/); assert.match(prompt, /cannot prove a health transformation/);
  assert.match(prompt, /canonical Script Director/);
  assert.doesNotMatch(prompt, /web_capture.py/);
  const publicPrompt = shortDirectionInstructions({ ...auto, mediaPolicy: { placement: "auto", sources: "public-web" } });
  assert.match(publicPrompt, /web_capture.py/); assert.match(publicPrompt, /exact official site/);
  assert.doesNotMatch(shortDirectionInstructions({ ...auto, supportingVideo: "off" }), /web_capture.py/);
  assert.match(shortDirectionInstructions({ ...auto, supportingVideo: "off" }), /Supporting video is off/);
});

test("media source restrictions survive all request paths without broadening legacy identity", () => {
  const legacy = { selection: "auto", supportingVideo: "source-first" } as const;
  assert.deepEqual(parseShortDirection(legacy, "short"), legacy);
  assert.deepEqual(shortMediaPolicy(legacy), { placement: "auto", sources: "local-only" });
  for (const sources of ["provided-only", "local-only", "public-web"] as const) {
    const shortDirection = { ...legacy, mediaPolicy: { placement: "auto" as const, sources } };
    const intent = validateIntent({ mode: "short", scope: "produced", lanes: {}, shortDirection });
    const roundTrip = parseAutoEditIntent(buildAutoEditRequest("/tmp/producer", intent))!;
    assert.deepEqual(roundTrip.shortDirection, shortDirection);
    assert.deepEqual(gateBundleOperatorIntent("produced", roundTrip).shortDirection, shortDirection);
    assert.deepEqual(buildStarterPlan({ sources: [] } as unknown as AssetManifest, intent).target.shortDirection, shortDirection);
    assert.match(shortDirectionInstructions(shortDirection), new RegExp(`Media sourcing policy: ${sources}`));
  }
  for (const mediaPolicy of [null, {}, { placement: "auto", sources: "generated" },
    { placement: "auto", sources: ["provided-only"] }, { placement: ["off"], sources: "local-only" },
    { placement: "auto", sources: "local-only", allowWeb: true }]) {
    assert.throws(() => parseShortDirection({ ...legacy, mediaPolicy }, "short"), /media policy/);
  }
  assert.throws(() => parseShortDirection({ ...legacy, supportingVideo: "off",
    mediaPolicy: { placement: "auto", sources: "public-web" } }, "short"), /conflicting/);
});

test("empty, conflicting and malformed style requests never become silent automatic selection", () => {
  for (const input of [null, [], { selection: "requested", request: " ", supportingVideo: "source-first" },
    { selection: "auto", request: "Nate", supportingVideo: "source-first" },
    { selection: "auto", supportingVideo: "web" }, { selection: "auto", supportingVideo: "off", extra: true }]) {
    assert.throws(() => parseShortDirection(input, "short"));
  }
  assert.throws(() => parseShortDirection({ selection: "auto", supportingVideo: "off" }, "longform"), /only for short/);
  assert.equal(parseShortDirection(undefined, "short"), undefined, "Old saved jobs retain their prior identity");
  for (const input of [{ selection: ["requested"], request: "Nate", supportingVideo: "off" },
    { selection: "auto", supportingVideo: ["off"] }]) assert.throws(() => parseShortDirection(input, "short"));
});

test("style preset selection preserves source and placement restrictions", () => {
  for (const sources of ["provided-only", "local-only", "public-web"] as const) {
    const current = { selection: "auto" as const, supportingVideo: "off" as const,
      mediaPolicy: { placement: "off" as const, sources } };
    const result = shortDirectionForStyle("Nate Herk", current);
    assert.deepEqual(result.mediaPolicy, current.mediaPolicy);
    assert.equal(result.supportingVideo, "off");
    assert.equal(result.request, "Nate Herk");
    assert.deepEqual(parseShortDirection(result, "short"), result);
  }
});
