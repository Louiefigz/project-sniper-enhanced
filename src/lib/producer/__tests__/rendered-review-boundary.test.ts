import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PROVIDER_MEDIA_PROFILE, providerMediaJail, SANDBOX_EXEC } from "../../../app/api/_lib/provider-media-jail";
import { runCodex } from "../../../app/api/_lib/codex-cli";
import { runLegacyBrainProcess } from "../../../app/api/producer/auto-edit/brain-review-process";
import { frameLabel, framesPerAttachment, renderedReviewAttachments }
  from "../../../app/api/producer/auto-edit/rendered-review-attachments";
import { claudeRenderedInput } from "../../../app/api/producer/auto-edit/rendered-review-invocation";

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const darwin = process.platform === "darwin";

function scratch(): string {
  return mkdtempSync(path.join(os.tmpdir(), "rendered-boundary-"));
}

test("the provider media profile denies video, audio and snapshots in any case, not stills or text", { skip: !darwin }, () => {
  const dir = scratch();
  try {
    const denied = ["final.mp4", "RAW.MOV", "take.Mp4", "voice.WAV", "bed.m4a", "abc.media", "clip.mkv", "cam.MTS"];
    const allowed = ["frame.jpg", "sheet.PNG", "audit_report.json", "plan.json"];
    for (const name of [...denied, ...allowed]) writeFileSync(path.join(dir, name), "x");
    for (const name of denied) {
      const jail = providerMediaJail("/bin/cat", [path.join(dir, name)]);
      const run = spawnSync(jail.bin, jail.args, { encoding: "utf8" });
      assert.notEqual(run.status, 0, `${name} must be unreadable`);
      assert.match(run.stderr, /Operation not permitted/);
    }
    for (const name of allowed) {
      const jail = providerMediaJail("/bin/cat", [path.join(dir, name)]);
      assert.equal(spawnSync(jail.bin, jail.args, { encoding: "utf8" }).stdout, "x", `${name} stays readable`);
    }
    const child = providerMediaJail("/bin/sh", ["-c", `/bin/cat '${path.join(dir, "final.mp4")}'`]);
    assert.notEqual(spawnSync(child.bin, child.args).status, 0, "children inherit the boundary");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("the jail wraps an absolute admitted binary through sandbox-exec with the shipped profile", { skip: !darwin }, () => {
  assert.deepEqual(providerMediaJail("/bin/echo", ["hi"]), { bin: SANDBOX_EXEC, args: ["-f", PROVIDER_MEDIA_PROFILE, "/bin/echo", "hi"] });
  assert.throws(() => providerMediaJail("echo", []), /absolute/);
});

test("a jailed review must be tool-less on both providers", async () => {
  await assert.rejects(runCodex({ prompt: "x", sandbox: "read-only", timeoutMs: 1000, tools: "default", jail: true }),
    /only to tool-less Codex runs/);
  await assert.rejects(runLegacyBrainProcess({ args: ["-p", "x", "--tools", "default"], cwd: os.tmpdir(), timeoutMs: 1000, jail: true }),
    /only to tool-less Claude runs/);
});

test("frames are attached individually up to 16, then in 2x2, 3x3 or 4x4 sheets; never dropped", () => {
  assert.equal(framesPerAttachment(1, 24), 1);
  assert.equal(framesPerAttachment(16, 24), 1);
  assert.equal(framesPerAttachment(17, 24), 4);
  assert.equal(framesPerAttachment(96, 24), 4);
  assert.equal(framesPerAttachment(137, 24), 9);
  assert.equal(framesPerAttachment(137, 20), 9);
  assert.equal(framesPerAttachment(384, 24), 16);
  assert.throws(() => framesPerAttachment(385, 24), /cannot run/);
  assert.throws(() => framesPerAttachment(0, 24), /at least one/);
  assert.equal(frameLabel("/x/graphic3_t012.500.jpg"), "graphic3 @ 12.5s");
});

test("many frames become labelled contact sheets that cover every frame", async () => {
  const dir = scratch();
  try {
    const frames = Array.from({ length: 30 }, (_, index) => {
      const frame = path.join(dir, `card${index}_t${String(index).padStart(3, "0")}.000.png`);
      writeFileSync(frame, PNG);
      return frame;
    });
    mkdirSync(path.join(dir, "work"));
    const result = await renderedReviewAttachments(frames, path.join(dir, "work"));
    assert.equal(result.frames.length, 8);
    assert.deepEqual(result.frames.flatMap((sheet) => sheet.labels).length, 30);
    assert.equal(result.frames[0].labels[0], "#1 card0 @ 0s");
    const input = JSON.parse(claudeRenderedInput("TEXT", result)) as { message: { content: Array<{ type: string; source?: { media_type: string } }> } };
    assert.deepEqual(input.message.content.map((block) => block.type), ["text", ...Array(8).fill("image")]);
    assert.equal(input.message.content[1].source?.media_type, "image/jpeg");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("non-image attachments are refused before any provider call", () => {
  const dir = scratch();
  try {
    const bogus = path.join(dir, "frame.jpg");
    writeFileSync(bogus, "not an image");
    assert.throws(() => claudeRenderedInput("x", { frames: [{ path: bogus, labels: ["#1"] }], reference: [] }), /not a JPEG or PNG/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
