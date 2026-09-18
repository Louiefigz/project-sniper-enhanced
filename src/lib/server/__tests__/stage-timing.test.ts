import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  journalStageEvent,
  stageTimingsPath,
  timedStage,
} from "../stage-timing";

interface TimingRow {
  stage: string;
  event: "start" | "end";
  ts: number;
  mono: number;
}

function rows(dir: string): TimingRow[] {
  return readFileSync(stageTimingsPath(dir), "utf8")
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as TimingRow);
}

async function run(): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-stage-timing-"));
  try {
    // Append: one parseable row with the cross-language shape, 0600 on create.
    assert.equal(journalStageEvent(dir, "planning_round", "start"), true);
    let parsed = rows(dir);
    assert.equal(parsed.length, 1);
    assert.equal(parsed[0].stage, "planning_round");
    assert.equal(parsed[0].event, "start");
    assert.equal(typeof parsed[0].ts, "number");
    assert.equal(typeof parsed[0].mono, "number");
    if (process.platform !== "win32") {
      assert.equal(statSync(stageTimingsPath(dir)).mode & 0o777, 0o600);
    }

    // Append-only: a second row never truncates the first.
    const before = readFileSync(stageTimingsPath(dir), "utf8");
    assert.equal(journalStageEvent(dir, "planning_round", "end"), true);
    assert.ok(readFileSync(stageTimingsPath(dir), "utf8").startsWith(before));
    assert.equal(rows(dir).length, 2);

    // timedStage: start before end, mono non-decreasing, value passed through.
    const value = await timedStage(dir, "authoring", async () => 7);
    assert.equal(value, 7);
    parsed = rows(dir);
    assert.deepEqual(
      parsed.map((row) => [row.stage, row.event]),
      [
        ["planning_round", "start"],
        ["planning_round", "end"],
        ["authoring", "start"],
        ["authoring", "end"],
      ],
    );
    const monos = parsed.map((row) => row.mono);
    assert.deepEqual(monos, [...monos].sort((left, right) => left - right));

    // timedStage: END is journaled even when the stage rejects.
    await assert.rejects(
      () => timedStage(dir, "qc_round", async () => {
        throw new Error("stage died");
      }),
      /stage died/,
    );
    const qc = rows(dir).filter((row) => row.stage === "qc_round");
    assert.deepEqual(qc.map((row) => row.event), ["start", "end"]);

    // Telemetry is best-effort: an unwritable anchor returns false, no throw.
    assert.equal(
      journalStageEvent(path.join(dir, "no", "such", "dir"), "x", "start"),
      false,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

run()
  .then(() => console.log("stage-timing.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
