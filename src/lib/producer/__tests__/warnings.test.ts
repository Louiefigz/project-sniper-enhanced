// Warnings-collector reducer assertions — run with:
//   npx tsx src/lib/producer/__tests__/warnings.test.ts
import assert from "node:assert/strict";
import { collectWarnings, WARNING_STATUSES, type WarningItem } from "../warnings";

// 1) Non-warning events return the SAME reference (cheap per-event fold).
{
  const prev: WarningItem[] = [];
  assert.equal(collectWarnings(prev, { status: "composited", ms: 12 }), prev);
  assert.equal(collectWarnings(prev, { event: "outputs" }), prev);
  assert.equal(collectWarnings(prev, {}), prev);
  assert.equal(collectWarnings(prev, { status: 42 }), prev, "non-string status ignored");
}

// 2) Every warning-class status is collected with a readable line.
{
  let acc: WarningItem[] = [];
  for (const status of WARNING_STATUSES) acc = collectWarnings(acc, { status, detail: "x" });
  assert.equal(acc.length, WARNING_STATUSES.size);
  assert.ok(acc.every((w) => WARNING_STATUSES.has(w.status) && w.text.includes(w.status)));
}

// 3) Appends preserve order and do not mutate the previous list.
{
  const first = collectWarnings([], { status: "proxy_failed", warning: "proxy encode failed" });
  const second = collectWarnings(first, { status: "music_not_applied", note: "assemble applies music" });
  assert.equal(first.length, 1);
  assert.equal(second.length, 2);
  assert.equal(second[0].status, "proxy_failed");
  assert.equal(second[1].status, "music_not_applied");
  assert.ok(second[0].text.includes("proxy encode failed"), "payload detail surfaces in the line");
}

// 4) Duplicate (status, text) collapses — same ref back.
{
  const one = collectWarnings([], { status: "refit_skipped", reason: "no base_plan" });
  const dup = collectWarnings(one, { status: "refit_skipped", reason: "no base_plan" });
  assert.equal(dup, one, "identical warning must not double-count");
  // same status, DIFFERENT detail → a second entry
  const other = collectWarnings(one, { status: "refit_skipped", reason: "other cause" });
  assert.equal(other.length, 2);
}

// 5) Palmier's generic fidelity warning survives the sync stream.
{
  const warnings = collectWarnings([], {
    status: "warning",
    warning: "captions are baked and cannot remain editable in Palmier",
  });
  assert.equal(warnings.length, 1);
  assert.equal(warnings[0].status, "warning");
  assert.match(warnings[0].text, /captions are baked/);
}

console.log("warnings.test.ts: all assertions passed");
