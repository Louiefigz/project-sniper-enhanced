/** Exercise the production route bridge; no provider or renderer is invoked. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { reviewedRenderEntry } from "@/app/api/producer/auto-edit/reviewed-render-entry";

function request(kind: string, body: unknown): NextRequest {
  return new NextRequest(`http://localhost:3000/api/producer/${kind}`, {
    method: "POST", headers: { host: "localhost:3000", origin: "http://localhost:3000", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

test("both old HTTP render routes use mandatory saved-plan review with the original local headers", async () => {
  for (const kind of ["render", "assemble"] as const) {
    let forwarded: Record<string, unknown> | undefined;
    const response = await reviewedRenderEntry(request(kind, kind === "render" ? { outDir: "/TEST/project/producer" }
      : { dir: "/TEST/project/producer" }), kind, async req => {
      assert.equal(req.nextUrl.pathname, "/api/producer/auto-edit");
      assert.equal(req.headers.get("origin"), "http://localhost:3000");
      forwarded = await req.json();
      return new Response("TEST controller stream", { status: 202 });
    });
    assert.equal(response.status, 202);
    assert.deepEqual(forwarded, { dir: "/TEST/project/producer", reviewSavedPlan: true, deliveryPolicy: "mp4-only" });
  }
});

test("inline plans, other project paths and review override flags cannot bypass the controller", async () => {
  let calls = 0;
  for (const body of [
    { outDir: "/TEST/project", planJson: {} },
    { outDir: "/TEST/project", planPath: "/TEST/other/edit_plan.json" },
    { outDir: "/TEST/project", reviewSavedPlan: false },
    { outDir: "/TEST/project", skipAudit: true },
    { outDir: "relative" }, null,
  ]) {
    const response = await reviewedRenderEntry(request("render", body), "render", async () => {
      calls += 1; return new Response("unexpected");
    });
    assert.equal(response.status, 409);
  }
  assert.equal(calls, 0);
});

test("controller refusal is returned unchanged and cannot fall back to the old direct renderer", async () => {
  const rejected = new Response("TEST pending cut approval", { status: 409 });
  const response = await reviewedRenderEntry(request("assemble", { dir: "/TEST/project" }), "assemble", async () => rejected);
  assert.equal(response, rejected);
});
