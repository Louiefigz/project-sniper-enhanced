import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import { seekShim } from "@/app/api/producer/comp-html/preview-shim";
import { parsePreviewHealth } from "@/components/producer/editor/use-preview-health";

type Event = { source?: object; data?: Record<string, unknown>; message?: string; target?: object };
function fixture() {
  const events: Record<string, (event: Event) => void> = {};
  const messages: Record<string, unknown>[] = [];
  const parent = { postMessage: (message: Record<string, unknown>) => messages.push(message) };
  const window = { __timelines: {} as Record<string, unknown>,
    addEventListener: (name: string, listener: (event: Event) => void) => { events[name] = listener; } };
  const document = { readyState: "loading" };
  const html = seekShim({ text: "</script><img src=x onerror=alert(1)>" });
  assert.equal((html.match(/<\/script>/g) ?? []).length, 1, "operator text cannot escape the script");
  runInNewContext(html.slice("<script>\n".length, -"\n</script>".length), { window, parent, document });
  const probe = (token = "current") => events.message({ source: parent, data: { type: "hf-preview-status", token } });
  return { events, messages, parent, window, document, probe };
}

const loading = fixture();
loading.probe();
assert.equal(loading.messages.length, 0, "do not mislabel normal loading as an error");
loading.document.readyState = "complete";
loading.probe();
assert.match(String(loading.messages[0].error), /No animation timeline/);
loading.window.__timelines.comp = { pause: () => ({ seek: () => undefined }) };
loading.probe();
assert.deepEqual(parsePreviewHealth(loading.messages[1], "current"), { ready: true, error: null });
assert.equal(parsePreviewHealth(loading.messages[1], "stale"), null);

const failed = fixture();
failed.events.error({ message: "gsap is not defined" });
assert.equal(failed.messages.length, 0, "remember startup failures before the parent handshake");
failed.document.readyState = "complete";
failed.window.__timelines.other = {};
failed.probe();
assert.equal(failed.messages[0].ready, false, "one registered timeline cannot hide another script's failure");
assert.equal(failed.messages[0].error, "gsap is not defined");
failed.events.message({ source: {}, data: { type: "hf-preview-status", token: "foreign" } });
assert.equal(failed.messages.length, 1, "other windows cannot alter the preview protocol");
failed.probe("new-document");
assert.equal(parsePreviewHealth(failed.messages[1], "current"), null, "old HTML state cannot bind a new document token");
assert.equal(parsePreviewHealth({ type: "hf-preview-health", token: "current", ready: true, error: "bad" }, "current"), null);
assert.equal(parsePreviewHealth(null, "current"), null);
assert.equal(parsePreviewHealth({ type: "hf-preview-health", token: "current", ready: false, error: "x".repeat(500) }, "current")?.error?.length, 400);
console.log("preview health protocol tests passed");
