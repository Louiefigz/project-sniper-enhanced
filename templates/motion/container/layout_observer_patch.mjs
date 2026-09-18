// Exact pinned source edits only. The upstream CLI is not changed on disk.
import { createHash } from "node:crypto";

export const CLI_SHA256 = "95be44729e244283cb685833a20b94e00c96aaafba7848b9182db01771477c78";
const HOST = "file:///opt/sniper-motion/container/layout_observer_host.mjs";
const PATCHES = [
  ["async function armStaticDedup(session, page, logInitPhase) {", "async function armStaticDedup(session, page, logInitPhase) {\n  session.staticDedupEnabled = false; return;"],
  ["    const screenshotStart = Date.now();", "    const __sniperLayoutCdp = await getCdpSession(page);\n    const __sniperLayoutBefore = await __sniperLayout.before(session, frameIndex, quantizedTime, __sniperLayoutCdp);\n    const screenshotStart = Date.now();"],
  ["    return { buffer: screenshotBuffer, quantizedTime, captureTimeMs };", "    await __sniperLayout.after(__sniperLayoutCdp, {index: frameIndex, time: quantizedTime, prior: __sniperLayoutBefore, buffer: screenshotBuffer});\n    return { buffer: screenshotBuffer, quantizedTime, captureTimeMs };"],
  ["            ensureFrameWritten(await currentEncoder.writeFrame(buffer), i2, currentEncoder);", "            ensureFrameWritten(await currentEncoder.writeFrame(buffer), i2, currentEncoder);\n            __sniperLayout.commit(i2, buffer);"],
];

export function instrument(source) {
  if (createHash("sha256").update(source).digest("hex") !== CLI_SHA256) throw new Error("layout observer requires exact HyperFrames CLI bytes");
  let updated = source;
  for (const [anchor, replacement] of PATCHES) {
    if (updated.split(anchor).length !== 2) throw new Error("layout observer capture anchor differs");
    updated = updated.replace(anchor, replacement);
  }
  return updated.replace("#!/usr/bin/env node\n", `#!/usr/bin/env node\nimport * as __sniperLayout from ${JSON.stringify(HOST)};\n`);
}
