import assert from "node:assert/strict";
import { parseReferenceUrl } from "../../../app/api/_lib/reference-fetch-policy";

for (const url of [
  "https://youtube.com/watch?v=abc",
  "https://www.youtube.com/shorts/abc",
  "https://youtu.be/abc",
  "https://www.instagram.com/reel/abc",
  "https://m.tiktok.com/v/abc",
]) {
  assert.equal(parseReferenceUrl(url).toString(), url);
}

for (const url of [
  "http://127.0.0.1/video.mp4",
  "http://youtube.com/watch?v=x",
  "http://localhost/video.mp4",
  "https://youtube.com.evil.test/watch?v=x",
  "https://example.com/video.mp4",
  "https://user:secret@youtube.com/watch?v=x",
  "file:///tmp/video.mp4",
  "https://youtube.com:8443/watch?v=x",
]) {
  assert.throws(() => parseReferenceUrl(url));
}
assert.throws(() => parseReferenceUrl(`https://youtube.com/watch?v=${"x".repeat(2100)}`), /too long/);

console.log("reference-fetch-policy.test.ts: all assertions passed");
