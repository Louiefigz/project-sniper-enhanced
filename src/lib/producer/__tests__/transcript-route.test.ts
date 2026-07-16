import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { GET } from "../../../app/api/producer/transcript/route";

function requestFor(filePath: string): NextRequest {
  return new NextRequest(
    `http://localhost:3000/api/producer/transcript?path=${encodeURIComponent(filePath)}`,
  );
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(tmpdir(), "sniper-transcript-route-"));
  try {
    const valid = path.join(root, "captions.srt");
    writeFileSync(valid, "1\n00:00:01,250 --> 00:00:02,500\nClear caption\n");
    const loaded = await GET(requestFor(valid));
    assert.equal(loaded.status, 200);
    assert.deepEqual(await loaded.json(), {
      available: true,
      cues: [{ start: 1.25, end: 2.5, text: "Clear caption" }],
    });

    rmSync(valid);
    const missing = await GET(requestFor(valid));
    assert.equal(missing.status, 404);
    assert.equal((await missing.json()).available, false);

    mkdirSync(valid);
    const unreadable = await GET(requestFor(valid));
    assert.equal(unreadable.status, 500);
    assert.match((await unreadable.json()).error, /could not be read/i);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("transcript-route.test.ts: all assertions passed"))
  .catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
