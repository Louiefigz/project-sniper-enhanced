// TEST-ONLY in-process invocation of the real guided-opening route handlers against a retained project.
// Not an HTTP-layer test: the user's Next dev server must not be restarted, so the handlers run here directly.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { NextRequest } from "next/server";
import { GET as statusGet } from "@/app/api/producer/guided-opening/status/route";
import { GET as mediaGet } from "@/app/api/producer/guided-opening/media/route";
import { parseGuidedOpeningStatus } from "@/lib/producer/guided-opening-client";

const dir = process.argv[2], core = process.argv[3];
const origin = "http://localhost:3327";
const headers = { host: "localhost:3327", origin, "sec-fetch-site": "same-origin", accept: "application/json" };
function request(path: string, extra: Record<string, string> = {}) {
  return new NextRequest(`${origin}${path}`, { headers: { ...headers, ...extra } });
}
async function main() {
  const started = performance.now();
  const status = await statusGet(request(`/api/producer/guided-opening/status?dir=${encodeURIComponent(dir)}`));
  const body = await status.json();
  console.log(JSON.stringify({ route: "status", http: status.status, ms: Math.round(performance.now() - started), state: body.state, ok: body.ok,
    error: body.error, openingApproved: body.openingApproved, approval: body.approval, journal: body.journal ? Object.keys(body.journal) : null,
    coreUrl: body.media?.core?.url?.slice(0, 120), timing: body.timing }));
  if (status.status === 200) {
    const parsed = parseGuidedOpeningStatus(body, dir);
    console.log(JSON.stringify({ route: "status", parsedByBrowserClient: parsed.state, mediaFrames: parsed.state === "ready-for-review" ? { core: parsed.media.core.videoFrames, review: parsed.media.review.videoFrames } : null }));
    if (parsed.state === "ready-for-review") {
      const url = parsed.media.core.url, t2 = performance.now();
      const media = await mediaGet(request(url, { range: "bytes=0-1023" }));
      const bytes = Buffer.from(await media.arrayBuffer());
      const onDisk = readFileSync(core).subarray(0, 1024);
      console.log(JSON.stringify({ route: "media", http: media.status, ms: Math.round(performance.now() - t2), contentRange: media.headers.get("content-range"),
        contentType: media.headers.get("content-type"), bytes: bytes.length, firstKbMatchesFile: createHash("sha256").update(bytes).digest("hex") === createHash("sha256").update(onDisk).digest("hex") }));
      const t3 = performance.now();
      const whole = await mediaGet(request(url));
      const all = Buffer.from(await whole.arrayBuffer());
      console.log(JSON.stringify({ route: "media", http: whole.status, ms: Math.round(performance.now() - t3), bytes: all.length,
        wholeSha256MatchesSelection: createHash("sha256").update(all).digest("hex") === parsed.media.core.mediaSha256 }));
      const bad = await mediaGet(request(url.replace(/mediaSha256=[0-9a-f]+/, `mediaSha256=${"0".repeat(64)}`)));
      console.log(JSON.stringify({ route: "media", wrongHash: bad.status }));
      const bad416 = await mediaGet(request(url, { range: "bytes=999999999-" }));
      console.log(JSON.stringify({ route: "media", badRange: bad416.status }));
    }
  }
}
main().catch((error) => { console.error(String(error)); process.exit(1); });
