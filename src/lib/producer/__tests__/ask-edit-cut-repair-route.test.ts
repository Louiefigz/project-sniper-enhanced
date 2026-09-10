import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { POST } from "../../../app/api/producer/ai-edit/route";

function request(intent: unknown): NextRequest {
  return new NextRequest("http://localhost/api/producer/ai-edit", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      host: "localhost",
      origin: "http://localhost",
    },
    body: JSON.stringify({
      dir: "/definitely/not/a/project-sniper-workspace",
      request: intent,
      scope: { lanes: ["cuts"] },
    }),
  });
}

async function run(): Promise<void> {
  const repair = await POST(request(
    "You stepped on one of my words here. Extend only that phrase.",
  ));
  assert.equal(repair.status, 409);
  const body = await repair.json();
  assert.equal(body.code, "FIRST_CLASS_CUT_REPAIR_ROUTE_REQUIRED");
  assert.match(body.error, /plan-only Ask Editor writer was not run/i);

  const ordinary = await POST(request("Trim the pause before the hook."));
  assert.equal(ordinary.status, 400);
  assert.match(String((await ordinary.json()).error), /dir not found/);

  const structured = await POST(request({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "analyze",
    target: { phrase: "the exact clipped phrase", occurrence: 1 },
  }));
  assert.equal(structured.status, 400);
  assert.match(String((await structured.json()).error), /dir not found/);

  const execution = await POST(request({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "execute",
    target: { phrase: "the exact clipped phrase", occurrence: 1 },
  }));
  assert.equal(execution.status, 400);
  assert.match(String((await execution.json()).error), /requires packageHash/);

  const reopen = await POST(request({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "reopen",
    target: { phrase: "the exact clipped phrase", occurrence: 1 },
  }));
  assert.equal(reopen.status, 400);
  assert.match(String((await reopen.json()).error),
    /reopen requires a canonical UUID/);

  const injectedEvidence = await POST(request({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode: "analyze",
    target: {
      phrase: "the exact clipped phrase",
      occurrence: 1,
      alignmentHash: "a".repeat(64),
    },
  }));
  assert.equal(injectedEvidence.status, 400);
  assert.match(
    String((await injectedEvidence.json()).error),
    /unsupported fields/,
  );
}

run()
  .then(() => console.log("ask-edit-cut-repair-route tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
