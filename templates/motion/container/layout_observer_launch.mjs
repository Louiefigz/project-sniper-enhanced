// Explicit sealed-container entry only; the normal render command is unchanged.
import { register } from "node:module";
register("./layout_observer_loader.mjs", import.meta.url);
await import("../node_modules/hyperframes/dist/cli.js");
