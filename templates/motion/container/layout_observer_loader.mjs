import { instrument } from "./layout_observer_patch.mjs";

const CLI = "file:///opt/sniper-motion/node_modules/hyperframes/dist/cli.js";

export async function load(url, context, nextLoad) {
  const loaded = await nextLoad(url, context);
  if (url !== CLI) return loaded;
  if (loaded.format !== "module" || !loaded.source) throw new Error("layout CLI module loader differs");
  return { ...loaded, source: instrument(Buffer.from(loaded.source).toString("utf8")) };
}
