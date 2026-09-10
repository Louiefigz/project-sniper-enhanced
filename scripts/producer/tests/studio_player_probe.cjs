/* Headless-Chrome probe for the Studio review PLAYER (test_studio_player_view).
 *
 * Drives the REAL Studio UI page, finds the preview iframe hosting the
 * generated review composition, seeks the runtime player to each requested
 * beat, and reports raw facts as one JSON object on stdout:
 * page errors, console errors, HTTP>=400 responses, gsap/timeline state,
 * per-beat slot visibility + child bbox coverage, stray raw text nodes,
 * video paint state, and a play/getTime advance check. Screenshots land in
 * the configured directory. Assertions live in the Python test, not here.
 *
 * Usage: node studio_player_probe.cjs <config.json>
 *   config: { puppeteerDir, chrome, url, shotsDir, settleMs,
 *             beats: [number, ...] }
 */
const fs = require("fs");
const path = require("path");

const config = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const puppeteer = require(config.puppeteerDir);

const WATCHDOG_MS = 90000;
const watchdog = setTimeout(() => {
  console.error("FATAL probe watchdog expired");
  process.exit(3);
}, WATCHDOG_MS);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function findHostFrame(page) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    for (const frame of page.frames()) {
      const ok = await frame.evaluate(() =>
        !!(window.__playerReady &&
           document.querySelector('[data-composition-id="review"]')))
        .catch(() => false);
      if (ok) return frame;
    }
    await sleep(500);
  }
  return null;
}

function beatFacts(beat) {
  const root = document.querySelector('[data-composition-id="review"]');
  const rootRect = root.getBoundingClientRect();
  const slots = [];
  for (const el of root.children) {
    if (el.tagName !== "DIV") continue;
    const cs = getComputedStyle(el);
    const kid = el.firstElementChild;
    const kr = kid ? kid.getBoundingClientRect() : null;
    slots.push({
      id: el.id,
      visible: cs.display !== "none" && cs.visibility !== "hidden" &&
        Number(cs.opacity) > 0.01,
      childTag: kid ? kid.tagName : null,
      childRect: kr ? [kr.x, kr.y, kr.width, kr.height] : null,
      coverage: kr && rootRect.width > 0 && rootRect.height > 0
        ? (Math.max(0, Math.min(kr.right, rootRect.right) -
                       Math.max(kr.left, rootRect.left)) *
           Math.max(0, Math.min(kr.bottom, rootRect.bottom) -
                       Math.max(kr.top, rootRect.top))) /
          (rootRect.width * rootRect.height)
        : 0,
    });
  }
  const rawText = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent.trim();
    if (text.length <= 120) continue;
    const parent = walker.currentNode.parentElement;
    if (!parent) continue;
    const tag = parent.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEMPLATE") continue;
    if (parent.closest("template, [data-hf-inner-root]")) continue;
    const rect = parent.getBoundingClientRect();
    rawText.push({
      parent: tag + "#" + (parent.id || ""),
      rect: [rect.x, rect.y, rect.width, rect.height],
      excerpt: text.slice(0, 120),
    });
  }
  const video = document.getElementById("review-base");
  let videoState = null;
  if (video) {
    videoState = { readyState: video.readyState,
                   currentTime: video.currentTime, maxChannel: null };
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 64; canvas.height = 36;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, 64, 36);
      const px = ctx.getImageData(0, 0, 64, 36).data;
      let max = 0;
      for (let i = 0; i < px.length; i += 4) {
        max = Math.max(max, px[i], px[i + 1], px[i + 2]);
      }
      videoState.maxChannel = max;
    } catch (err) {
      videoState.sampleError = String(err).slice(0, 160);
    }
  }
  return {
    beat,
    playerTime: window.__player ? window.__player.getTime() : null,
    stage: [rootRect.width, rootRect.height],
    gsapType: typeof window.gsap,
    timelineKeys: Object.keys(window.__timelines || {}),
    slots, rawText, video: videoState,
  };
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: config.chrome,
    headless: "shell",
    args: ["--no-sandbox", "--window-size=1800,1100"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1800, height: 1100 });
  const pageErrors = [];
  const consoleErrors = [];
  const badResponses = [];
  page.on("pageerror", (err) => pageErrors.push(String(err).slice(0, 300)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 300));
  });
  page.on("response", (res) => {
    if (res.status() >= 400) {
      badResponses.push("HTTP" + res.status() + " " + res.url().slice(0, 160));
    }
  });

  const result = { hostFrameFound: false, beats: [], play: null };
  await page.goto(config.url, { waitUntil: "networkidle2", timeout: 45000 });
  const frame = await findHostFrame(page);
  if (frame) {
    result.hostFrameFound = true;
    fs.mkdirSync(config.shotsDir, { recursive: true });
    for (const beat of config.beats) {
      await frame.evaluate((t) => window.__player.seek(t), beat);
      await sleep(config.settleMs);
      result.beats.push(await frame.evaluate(beatFacts, beat));
      await page.screenshot({
        path: path.join(config.shotsDir,
                        "beat-" + beat.toFixed(2).replace(".", "_") + ".png"),
      });
    }
    const before = await frame.evaluate(() => window.__player.getTime());
    await frame.evaluate(() => window.__player.play());
    await sleep(900);
    const after = await frame.evaluate(() => {
      const t = window.__player.getTime();
      window.__player.pause();
      return t;
    });
    result.play = { before, after };
  }
  result.pageErrors = pageErrors;
  result.consoleErrors = consoleErrors;
  result.badResponses = badResponses;
  console.log(JSON.stringify(result));
  await browser.close();
  clearTimeout(watchdog);
})().catch((err) => {
  console.error("FATAL", err);
  process.exit(2);
});
