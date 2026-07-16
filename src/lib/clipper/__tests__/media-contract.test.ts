import assert from "node:assert/strict";
import { parseFrameRate, parseVideoProbe } from "@/lib/server/clipper-media-probe";
import { consumeTranscriptionResponse, decorateTranscriptionWorkerLine } from "../transcription-stream";
import { generateFCPXML } from "../xml";
import type { Source, VideoMetadata } from "../types";
import { buildEditPrompt, DEFAULT_EDIT_REQUEST } from "@/prompts/clipper/default-edit";

const media: VideoMetadata = {
  duration: 12.5,
  frameRate: { numerator: 24000, denominator: 1001 },
  width: 3840,
  height: 2160,
};

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

assert.deepEqual(parseFrameRate("60000/2002"), { numerator: 30000, denominator: 1001 });
assert.equal(parseFrameRate("0/0"), null);

const probed = parseVideoProbe(JSON.stringify({
  streams: [{
    width: 3840,
    height: 2160,
    r_frame_rate: "30000/1001",
    avg_frame_rate: "2997/100",
    duration: "9.500000",
  }],
  format: { duration: "10.000000" },
}));
assert.deepEqual(probed, {
  duration: 9.5,
  frameRate: { numerator: 30000, denominator: 1001 },
  width: 3840,
  height: 2160,
});
assert.throws(() => parseVideoProbe('{"streams":[{"width":1920,"height":1080,"r_frame_rate":"0/0"}]}'));

const decorated = decorateTranscriptionWorkerLine(
  '{"status":"done","transcript":[],"fps":0}', media,
);
assert.equal(decorated.done, true);
assert.deepEqual(JSON.parse(decorated.payload).media, media);
assert.equal(JSON.parse(decorated.payload).fps, 24000 / 1001);

async function testStreamContract(): Promise<void> {
  const doneJson = JSON.stringify({ status: "done", transcript: [], media });
  const progress: string[] = [];
  const done = await consumeTranscriptionResponse(
    sseResponse([": keepalive\n\ndata: {\"status\":\"transcribing\"}\n", `\ndata: ${doneJson}\n\n`]),
    (event) => progress.push(event.status ?? "unknown"),
  );
  assert.deepEqual(progress, ["transcribing", "done"]);
  assert.deepEqual(done.media.frameRate, media.frameRate);

  await assert.rejects(
    consumeTranscriptionResponse(sseResponse(["data: {\"status\":\"transcribing\"}\n\n"]), () => {}),
    /before a terminal done event/,
  );
  await assert.rejects(
    consumeTranscriptionResponse(sseResponse([`data: ${doneJson}\n\ndata: {\"error\":\"worker failed\"}\n\n`]), () => {}),
    /worker failed/,
  );
  await assert.rejects(
    consumeTranscriptionResponse(sseResponse(['{"error":"probe failed"}'], 422), () => {}),
    /probe failed/,
  );
}

const source: Source = {
  angles: [{ id: "A", filePath: "/tmp/source.mov", audioSource: true }],
  duration: media.duration,
  fps: media.frameRate.numerator / media.frameRate.denominator,
  frameRate: media.frameRate,
  width: media.width,
  height: media.height,
  audioChannels: 1,
};
const xml = generateFCPXML([{ start: 1, end: 2, text: "Exact metadata" }], source);
assert.match(xml, /frameDuration="1001\/24000s" width="3840" height="2160"/);
assert.doesNotMatch(xml, /width="1920" height="1080"/);

assert.doesNotMatch(DEFAULT_EDIT_REQUEST, /call-in|caller/i);
assert.match(
  buildEditPrompt("Keep the product demo and remove the setup chatter."),
  /Keep the product demo and remove the setup chatter\./,
);

testStreamContract().then(() => {
  console.log("media-contract.test.ts: all assertions passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
