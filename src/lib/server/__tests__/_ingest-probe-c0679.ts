// TEST-ONLY in-process invocation of the real ingest route (GUI path) for the isolated C0679 qualification project.
// The source is referenced in place (>2 GiB rule); transcription is local whisper; no paid provider is reachable.
import { NextRequest } from "next/server";
import { POST as ingestPost } from "@/app/api/producer/ingest/route";

const inputPath = process.argv[2];
const origin = "http://localhost:3327";
const intent = { mode: "longform", scope: "produced", lanes: { motion: "off", transitions: "off", captions: "off", broll: "off" }, music: false };
async function main() {
  const started = Date.now();
  const request = new NextRequest(`${origin}/api/producer/ingest`, { method: "POST",
    headers: { host: "localhost:3327", origin, "sec-fetch-site": "same-origin", "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify({ inputPath, noTranscribe: false, intent }) });
  const response = await ingestPost(request);
  console.log(JSON.stringify({ http: response.status, contentType: response.headers.get("content-type") }));
  if (!response.body) { console.log(await response.text()); return; }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
      if (!line) continue;
      const payload = line.startsWith("data:") ? line.slice(5).trim() : line;
      const elapsed = ((Date.now() - started) / 1000).toFixed(1);
      try {
        const event = JSON.parse(payload) as Record<string, unknown>;
        const short = { ...event }; if (short.manifest) short.manifest = "(manifest)";
        console.log(`${elapsed}s ${JSON.stringify(short).slice(0, 600)}`);
      } catch { console.log(`${elapsed}s raw ${payload.slice(0, 300)}`); }
    }
  }
  console.log(JSON.stringify({ done: true, wallS: (Date.now() - started) / 1000 }));
}
main().catch((error) => { console.error(String(error)); process.exit(1); });
