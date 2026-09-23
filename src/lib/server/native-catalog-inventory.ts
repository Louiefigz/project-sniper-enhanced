import { execFileSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { objectValue } from "@/lib/producer/contracts/validation";

/** Complete inventory from the existing Python discovery; no downloads or HTML execution. */
export function nativeCatalogInventory() {
  const raw = execFileSync(pythonInterpreter(), [path.join(SCRIPTS_DIR, "producer/graphics/catalog_discovery_cli.py"), "inventory"],
    { encoding: "utf8", timeout: 45_000, maxBuffer: 16 * 1024 * 1024 });
  const inventory = objectValue(JSON.parse(raw), "catalog inventory");
  if (!Array.isArray(inventory.items) || inventory.limited !== false
      || inventory.total !== inventory.items.length || inventory.returned !== inventory.total) throw new Error("Catalog inventory is incomplete");
  return inventory;
}

