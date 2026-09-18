// Live capture acknowledgment, not a second seek/render or a serialized approval.
import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, fsyncSync, openSync, readSync, writeFileSync } from "node:fs";
import { browserExpression } from "./layout_observer_browser.mjs";
import { CLI_SHA256 } from "./layout_observer_patch.mjs";

export const POLICY = "sealed-agenda-css-layout-v1";
export const PIPELINE_POLICY = "sealed-pipeline-css-layout-v1";
const COMPOSITIONS = { [POLICY]: "compositions/agenda-slide.html", [PIPELINE_POLICY]: "compositions/nateherk-pipeline.html" };
export const FILES = ["layout_observer_browser.mjs", "layout_observer_host.mjs", "layout_observer_launch.mjs", "layout_observer_loader.mjs", "layout_observer_patch.mjs"];
const MAX_BYTES = 16 * 1024 * 1024;
const sha = (value) => createHash("sha256").update(value).digest("hex");

export function parseRequest(encoded) {
  if (typeof encoded !== "string" || encoded.length > 8192 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new Error("layout request encoding is invalid");
  const raw = Buffer.from(encoded, "base64");
  if (raw.toString("base64") !== encoded) throw new Error("layout request is not canonical base64");
  const value = JSON.parse(raw.toString("utf8"));
  const keys = ["schemaVersion", "profile", "snapshotSha256", "composition", "frameRate", "totalFrames", "width", "height"];
  if (!value || typeof value !== "object" || Object.keys(value).sort().join() !== keys.sort().join()) throw new Error("layout request fields differ");
  const rate = typeof value.frameRate === "string" ? /^([1-9][0-9]{0,5})\/([1-9][0-9]{0,5})$/.exec(value.frameRate) : null;
  if (value.schemaVersion !== 1 || typeof value.profile !== "string" || !Object.hasOwn(COMPOSITIONS, value.profile)
    || value.composition !== COMPOSITIONS[value.profile] || typeof value.snapshotSha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(value.snapshotSha256)) throw new Error("layout request profile differs");
  if (!rate || value.width !== 1920 || value.height !== 1080 || !Number.isSafeInteger(value.totalFrames) || value.totalFrames < 1 || value.totalFrames > 3600) throw new Error("layout request clock/canvas unsupported");
  const num = Number(rate[1]), den = Number(rate[2]);
  if (gcd(num, den) !== 1 || num / den > 60 || value.totalFrames * den / num > 60) throw new Error("layout request exceeds original bounded frame profile");
  return { value, raw, num, den };
}

function gcd(a, b) {
  while (b) [a, b] = [b, a % b];
  return a;
}

function heldFile(path, limit) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.size <= 0 || info.size > limit) throw new Error("layout held file shape/size differs");
    const hash = createHash("sha256"), chunk = Buffer.alloc(1024 * 1024);
    let count = 0, size = 0;
    while ((count = readSync(fd, chunk, 0, chunk.length, null)) > 0) { hash.update(chunk.subarray(0, count)); size += count; }
    const after = fstatSync(fd);
    if (size !== info.size || after.size !== info.size || after.mtimeMs !== info.mtimeMs || after.ctimeMs !== info.ctimeMs) throw new Error("layout held file changed while hashing");
    return { sha256: hash.digest("hex"), sizeBytes: size };
  } finally { closeSync(fd); }
}

export function createRecorder(request) {
  const frames = [], inventory = new Map();
  let pending = null, bytes = 0;
  return {
    stage(index, time, value, buffer) {
      if (!Number.isSafeInteger(index) || index < 0 || index >= request.value.totalFrames || Math.abs(time - index * request.den / request.num) > 1e-9) throw new Error("layout seek clock differs");
      pending = { frameIndex: index, timeNumerator: String(index * request.den), timeDenominator: String(request.num), captureSha256: sha(buffer), ...value };
    },
    commit(index, buffer) {
      if (!pending || pending.frameIndex !== index || index !== frames.length || pending.captureSha256 !== sha(buffer)) throw new Error("layout capture/write acknowledgment differs");
      const roles = pending.roles.map(({ id, text }) => ({ id, text }));
      if (index && JSON.stringify(roles) !== JSON.stringify([...inventory.values()])) throw new Error("layout actual text/role inventory changed");
      for (const role of roles) inventory.set(role.id, role);
      bytes += Buffer.byteLength(JSON.stringify(pending));
      if (bytes > MAX_BYTES - 16384) throw new Error("layout frame evidence exceeds byte ceiling");
      frames.push(pending); pending = null;
    },
    finish() {
      if (frames.length !== request.value.totalFrames || !inventory.size) throw new Error("layout output lacks complete actual written frame coverage");
      const visible = [...inventory.keys()].every((id) => frames.some((frame) => frame.roles.some((r) => r.id === id && r.opacity > 0 && r.bounds)));
      const clean = visible && frames.every((frame) => !frame.issues.length && frame.roles.every((role) => !role.issues.length));
      return { frames, roleInventory: [...inventory.values()], framesObserved: frames.length, status: clean ? "observed" : "unqualified" };
    },
  };
}

let live = null;
function current() {
  if (live) return live;
  const request = parseRequest(process.env.SNIPER_LAYOUT_REQUEST);
  if (request.value.snapshotSha256 !== process.env.SNIPER_INPUT_SHA256) throw new Error("layout request is not bound to actual sealed archive");
  const sources = FILES.map((name) => ({ path: `/opt/sniper-motion/container/${name}`, ...heldFile(`/opt/sniper-motion/container/${name}`, 65536) }));
  live = { request, sources, recorder: createRecorder(request) };
  process.once("exit", sealOnExit);
  return live;
}

function sealOnExit(code) {
  if (code !== 0 || !live) return;
  try {
    const output = live.recorder.finish();
    const sources = FILES.map((name) => ({ path: `/opt/sniper-motion/container/${name}`, ...heldFile(`/opt/sniper-motion/container/${name}`, 65536) }));
    if (JSON.stringify(sources) !== JSON.stringify(live.sources)) throw new Error("layout observer implementation changed");
    const result = { schemaVersion: 1, kind: "sealed-animation-layout-observation", policy: live.request.value.profile,
      scope: "actual-css-range-envelopes-not-glyph-pixel-legibility-or-approval", request: live.request.value,
      requestSha256: sha(live.request.raw), cliSha256: CLI_SHA256, observerSources: sources,
      media: heldFile("/output/render.mp4", 512 * 1024 * 1024), ...output };
    const raw = Buffer.from(JSON.stringify(result));
    if (raw.length > MAX_BYTES) throw new Error("layout result exceeds byte ceiling");
    const fd = openSync("/output/layout-observation.json", constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); }
  } catch (error) { process.stderr.write(`layout observation failed: ${error.message}\n`); process.exitCode = 1; }
}

const worlds = new WeakMap();
async function isolatedObservation(cdp) {
  if (!worlds.has(cdp)) {
    const tree = await cdp.send("Page.getFrameTree");
    const world = await cdp.send("Page.createIsolatedWorld", {
      frameId: tree.frameTree.frame.id, worldName: "sniper-sealed-layout-v1", grantUniveralAccess: false,
    });
    worlds.set(cdp, world.executionContextId);
  }
  const result = await cdp.send("Runtime.evaluate", {
    expression: browserExpression(current().request.value.profile), contextId: worlds.get(cdp), returnByValue: true, awaitPromise: true,
  });
  if (result.exceptionDetails || !result.result || result.result.type !== "object" || !result.result.value) throw new Error("isolated native DOM observation failed");
  return result.result.value;
}

export async function before(session, index, time, cdp) {
  current();
  if (session.options.width !== 1920 || session.options.height !== 1080) throw new Error("layout capture canvas differs");
  const value = await isolatedObservation(cdp);
  return { index, time, value };
}

export async function after(cdp, context) {
  const { index, time, prior, buffer } = context;
  const value = await isolatedObservation(cdp);
  if (prior.index !== index || prior.time !== time || JSON.stringify(prior.value) !== JSON.stringify(value)) throw new Error("layout changed across actual frame capture");
  current().recorder.stage(index, time, value, buffer);
}

export function commit(index, buffer) { current().recorder.commit(index, buffer); }
