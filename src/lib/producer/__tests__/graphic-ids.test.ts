// reconcileGraphicIds + newGraphicId + graphicBlocks id-addressing assertions.
// Run with:  npx tsx src/lib/producer/__tests__/graphic-ids.test.ts
import assert from "node:assert/strict";
import {
  GRAPHIC_ID_RE,
  graphicBlocks,
  newGraphicId,
  reconcileGraphicIds,
  type EditPlan,
  type GraphicEntry,
} from "../edit-plan";

const g = (over: Partial<GraphicEntry> = {}): GraphicEntry => ({
  outStart: 0,
  outEnd: 4,
  kind: "stat-card",
  spec: { value: "42%" },
  ...over,
});
const plan = (...track: GraphicEntry[]): EditPlan => ({ graphicsTrack: track });

// ---- newGraphicId: well-formed + unique ----
{
  const ids = new Set<string>();
  for (let i = 0; i < 5000; i++) {
    const id = newGraphicId();
    assert.match(id, GRAPHIC_ID_RE, `newGraphicId is well-formed: ${id}`);
    ids.add(id);
  }
  assert.ok(ids.size > 4990, `5000 ids are ~all unique (got ${ids.size})`);
}

// ---- back-compat: a legacy id-less plan gets one unique id per entry ----
{
  const { plan: out, minted, reminted } = reconcileGraphicIds(plan(g(), g({ kind: "chip-row" }), g()));
  assert.equal(minted, 3, "three missing ids minted");
  assert.equal(reminted, 0, "nothing re-minted");
  const ids = out.graphicsTrack!.map((x) => x.id!);
  assert.ok(ids.every((id) => GRAPHIC_ID_RE.test(id)), "all ids well-formed");
  assert.equal(new Set(ids).size, 3, "all ids unique");
  // Non-id fields are untouched (back-compat: only `id` is added).
  assert.equal(out.graphicsTrack![1].kind, "chip-row", "kind preserved");
  assert.deepEqual(out.graphicsTrack![0].spec, { value: "42%" }, "spec preserved");
}

// ---- idempotent: a fully-id'd plan reconciles to the SAME object (no churn) ----
{
  const once = reconcileGraphicIds(plan(g(), g(), g())).plan;
  const twice = reconcileGraphicIds(once);
  assert.equal(twice.minted, 0, "second pass mints nothing");
  assert.equal(twice.reminted, 0, "second pass re-mints nothing");
  assert.equal(twice.plan, once, "unchanged plan returns the SAME reference (no re-render churn)");
  assert.deepEqual(
    twice.plan.graphicsTrack!.map((x) => x.id),
    once.graphicsTrack!.map((x) => x.id),
    "ids are stable across reconciles",
  );
}

// ---- duplicate ids: the first survives, later collisions are re-minted ----
{
  const dup = "g-aaaabbbb";
  const { plan: out, reminted } = reconcileGraphicIds(plan(g({ id: dup }), g({ id: dup }), g({ id: dup })));
  assert.equal(reminted, 2, "two duplicate collisions re-minted");
  const ids = out.graphicsTrack!.map((x) => x.id!);
  assert.equal(ids[0], dup, "first occurrence keeps the id");
  assert.equal(new Set(ids).size, 3, "no duplicates remain");
  assert.ok(ids.every((id) => GRAPHIC_ID_RE.test(id)), "re-minted ids are well-formed");
}

// ---- AI-fabricated / malformed ids are stripped and re-minted ----
{
  // The model invents "graphic-1" (wrong format) for a new entry; a real id is kept.
  const real = "g-12345678";
  const { plan: out, minted, reminted } = reconcileGraphicIds(
    plan(g({ id: real }), g({ id: "graphic-1" }), g({ id: "" }), g()),
  );
  assert.equal(reminted, 2, "malformed 'graphic-1' + empty-string id both re-minted");
  assert.equal(minted, 1, "the missing id minted");
  const ids = out.graphicsTrack!.map((x) => x.id!);
  assert.equal(ids[0], real, "the well-formed id is preserved");
  assert.notEqual(ids[1], "graphic-1", "the fabricated id is replaced");
  assert.ok(ids.every((id) => GRAPHIC_ID_RE.test(id)), "every id ends up well-formed");
  assert.equal(new Set(ids).size, 4, "all unique");
}

// ---- a partially-id'd plan mints only the gaps, preserves the rest ----
{
  const keep = "g-cafebabe";
  const { plan: out, minted, reminted } = reconcileGraphicIds(plan(g({ id: keep }), g(), g({ id: keep })));
  // 3rd entry duplicates the 1st's id → re-minted; 2nd is missing → minted.
  assert.equal(minted, 1, "one missing id minted");
  assert.equal(reminted, 1, "one duplicate re-minted");
  assert.equal(out.graphicsTrack![0].id, keep, "first keeps its id");
  assert.notEqual(out.graphicsTrack![2].id, keep, "duplicate third is re-minted");
}

// ---- no graphicsTrack / empty track: no-op, same reference ----
{
  const empty: EditPlan = { cutTrack: [{ sourceId: "raw", start: 0, end: 10 }] };
  const r = reconcileGraphicIds(empty);
  assert.equal(r.plan, empty, "no graphicsTrack → same reference");
  assert.equal(r.minted, 0, "nothing minted");
  const emptyTrack: EditPlan = { graphicsTrack: [] };
  assert.equal(reconcileGraphicIds(emptyTrack).plan, emptyTrack, "empty track → same reference");
}

// ---- graphicBlocks carries the id and drops unreconciled (id-less) entries ----
{
  const reconciled = reconcileGraphicIds(plan(g({ outStart: 1, outEnd: 3 }), g({ outStart: 5, outEnd: 9 }))).plan;
  const blocks = graphicBlocks(reconciled);
  assert.equal(blocks.length, 2, "one block per id'd entry");
  assert.ok(blocks.every((b) => GRAPHIC_ID_RE.test(b.id)), "each block exposes its id");
  assert.deepEqual(
    blocks.map((b) => b.id),
    reconciled.graphicsTrack!.map((x) => x.id),
    "block ids match the track order",
  );
  // An id-less entry is not addressable, so it is skipped (never index-keyed).
  const mixed: EditPlan = { graphicsTrack: [g({ id: "g-11112222" }), g()] };
  assert.equal(graphicBlocks(mixed).length, 1, "id-less entry is dropped from blocks");
}

// ---- semanticBeatId lets code mint and persist the decision's stable graphicId ----
{
  const beatId = "intro-abc123def456";
  const input: EditPlan = {
    graphicsTrack: [g({ semanticBeatId: beatId })],
    graphicsDecisions: [{
      beatId, decision: "graphic", kind: "stat-card",
      reason: "This exact graphic realizes the spoken beat.",
    }],
  };
  const result = reconcileGraphicIds(input);
  const graphicId = result.plan.graphicsTrack![0].id;
  assert.equal(result.bound, 1, "controller binds one new decision");
  assert.match(graphicId!, GRAPHIC_ID_RE);
  assert.equal(result.plan.graphicsDecisions![0].graphicId, graphicId);
  const again = reconcileGraphicIds(result.plan);
  assert.equal(again.plan, result.plan, "bound plan is stable and does not churn");
}

// ---- ambiguous semanticBeatId is left unbound for the deterministic gate ----
{
  const beatId = "intro-duplicate111";
  const input: EditPlan = {
    graphicsTrack: [g({ semanticBeatId: beatId }), g({ semanticBeatId: beatId })],
    graphicsDecisions: [{
      beatId, decision: "graphic", kind: "stat-card",
      reason: "Ambiguous binding must fail later rather than guess.",
    }],
  };
  const result = reconcileGraphicIds(input);
  assert.equal(result.bound, 0);
  assert.equal(result.plan.graphicsDecisions![0].graphicId, undefined);
}

console.log("graphic-ids.test.ts: all assertions passed");
