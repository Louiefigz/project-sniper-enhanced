import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { POST } from "../../../app/api/producer/transcript-authority/route";
import { acquireProjectMutationLease } from "../project-mutation-lease";

async function main(): Promise<void> {
  const root = fs.mkdtempSync(
    path.join(os.tmpdir(), "sniper-transcript-route-"));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  const candidate = path.join(root, "candidate-manifest.json");
  fs.mkdirSync(producer);
  fs.mkdirSync(source);
  fs.writeFileSync(path.join(root, "project.json"), JSON.stringify({
    origin: "raw", history: [],
  }));
  fs.writeFileSync(path.join(source, "asset_manifest.json"), "{}\n");
  fs.writeFileSync(path.join(source, "raw-1.transcript.json"), "prior\n");
  fs.writeFileSync(candidate, "{}\n");
  const held = acquireProjectMutationLease(root, "test active Auto Edit");
  assert.ok(held.lease);
  try {
  const request = new NextRequest(
    "http://127.0.0.1:3101/api/producer/transcript-authority",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        host: "127.0.0.1:3101",
        origin: "http://127.0.0.1:3101",
        "sec-fetch-site": "same-origin",
      },
      body: JSON.stringify({
        dir: root,
        candidateManifest: candidate,
        sourceId: "raw-1",
      }),
    },
  );
    const response = await POST(request);
    const body = await response.json() as Record<string, unknown>;
    assert.equal(response.status, 409);
    assert.equal(body.code, "PROJECT_MUTATION_BUSY");
    assert.equal(
      fs.readFileSync(
        path.join(source, "raw-1.transcript.json"), "utf8"),
      "prior\n",
    );
  } finally {
    held.lease?.release();
    fs.rmSync(root, { recursive: true, force: true });
  }
}

main()
  .then(() => console.log("producer transcript authority route tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
