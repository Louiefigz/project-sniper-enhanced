import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { runAuditGate, validAuditSummary } from "../../../app/api/_lib/audit-gate";
import { audioAuditFixture } from "./audit-audio-fixture";

const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-audit-contract-"));

async function run(): Promise<void> {
  const report = path.join(dir, "audit_report.md");
  const machine = path.join(dir, "audit_report.json");
  writeFileSync(report, "report");
  writeFileSync(machine, JSON.stringify(audioAuditFixture()));
  assert.equal(validAuditSummary({
    status: "done", overall: "pass", failed: 0, report, machine,
  }), null);
  assert.match(validAuditSummary({ overall: "pass", failed: 0, report, machine })!, /not a done/);
  assert.match(validAuditSummary({
    status: "done", overall: "error", failed: 0, report, machine,
  })!, /unknown overall/);
  assert.match(validAuditSummary({
    status: "done", overall: "pass", failed: 0, report, machine: `${machine}.missing`,
  })!, /evidence is missing/);
  assert.match(validAuditSummary({
    status: "done", overall: "pass", report, machine,
  })!, /failed-check count/);
  assert.match(validAuditSummary({
    status: "done", overall: "pass", failed: 0, report, machine,
  }, "b".repeat(64))!, /expected candidate/);
  assert.match(validAuditSummary({
    status: "done", overall: "pass", failed: 0, report, machine,
  }, null)!, /expected candidate/);
  writeFileSync(machine, JSON.stringify({ overall: "pass", checks: [] }));
  assert.match(validAuditSummary({
    status: "done", overall: "pass", failed: 0, report, machine,
  })!, /policy v2/);

  // A hung audit is SIGTERMed and reported as a failed audit, never left
  // running unbounded. Python interpreter startup always outlives a 1 ms
  // budget, so this exercises the real timeout + process-group termination.
  const timedOut = await runAuditGate(dir, 1);
  assert.match(String(timedOut.failure), /audit timed out after 1 ms/);
  assert.equal(timedOut.event.overall, "error");
  assert.match(String(timedOut.event.message), /audit timed out/);
}

run()
  .then(() => console.log("audit-gate-contract.test.ts: all assertions passed"))
  .finally(() => rmSync(dir, { recursive: true, force: true }));
