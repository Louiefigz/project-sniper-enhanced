import assert from "node:assert/strict";
import { NextRequest } from "next/server";

import { proxy } from "../../../proxy";

const originalMode = process.env.SNIPER_EXECUTION_MODE;

try {
  process.env.SNIPER_EXECUTION_MODE = "local";

  const blocked = proxy(
    new NextRequest("http://127.0.0.1:3000/api/producer/comps", {
      headers: { host: "sniper.example" },
    }),
  );
  assert.equal(blocked.status, 403);
  assert.equal(blocked.headers.get("cache-control"), "no-store, max-age=0");
  assert.equal(blocked.headers.get("x-content-type-options"), "nosniff");

  const allowed = proxy(
    new NextRequest("http://localhost:3000/api/producer/projects", {
      method: "POST",
      headers: {
        host: "localhost:3000",
        origin: "http://localhost:3000",
        "sec-fetch-site": "same-origin",
        "content-type": "application/json",
      },
      body: "{}",
    }),
  );
  assert.equal(allowed.status, 200);
  assert.equal(allowed.headers.get("x-middleware-next"), "1");
  assert.equal(allowed.headers.get("cross-origin-resource-policy"), "same-origin");

  process.env.SNIPER_EXECUTION_MODE = "live";
  const liveMode = proxy(
    new NextRequest("http://127.0.0.1:3000/api/producer/comps", {
      headers: { host: "sniper.example" },
    }),
  );
  assert.equal(liveMode.status, 200);
  assert.equal(liveMode.headers.get("x-middleware-next"), "1");
  assert.equal(liveMode.headers.get("cache-control"), null);
} finally {
  if (originalMode === undefined) {
    delete process.env.SNIPER_EXECUTION_MODE;
  } else {
    process.env.SNIPER_EXECUTION_MODE = originalMode;
  }
}

console.log("local-proxy.test.ts: all assertions passed");
