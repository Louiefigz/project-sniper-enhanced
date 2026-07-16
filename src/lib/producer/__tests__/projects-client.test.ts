import assert from "node:assert/strict";

import {
  loadProjects,
  ProjectsClientError,
  type ProjectsClientDeps,
} from "../projects-client";

interface TestProject { dir: string }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function htmlResponse(status = 503): Response {
  return new Response("<html>temporary dev response</html>", {
    status,
    headers: { "content-type": "text/html" },
  });
}

function depsFrom(responses: Array<Response | Error>) {
  let calls = 0;
  let delays = 0;
  const requests: RequestInit[] = [];
  const deps: ProjectsClientDeps = {
    fetcher: async (_input, init) => {
      requests.push(init ?? {});
      const response = responses[calls++];
      if (!response) throw new Error("missing fixture response");
      if (response instanceof Error) throw response;
      return response;
    },
    delay: async () => { delays += 1; },
  };
  return { deps, requests, calls: () => calls, delays: () => delays };
}

async function expectClientError(responses: Array<Response | Error>) {
  const fixture = depsFrom(responses);
  const error = await loadProjects<TestProject>(new AbortController().signal, fixture.deps)
    .then(() => null, (reason: unknown) => reason);
  assert.ok(error instanceof ProjectsClientError);
  return { error, calls: fixture.calls() };
}

async function testValidJson(): Promise<void> {
  const fixture = depsFrom([jsonResponse({ projects: [{ dir: "/project" }] })]);
  const projects = await loadProjects<TestProject>(new AbortController().signal, fixture.deps);
  assert.deepEqual(projects, [{ dir: "/project" }]);
  assert.equal(fixture.calls(), 1);
  assert.equal(fixture.requests[0]?.cache, "no-store");
}

async function testTransientResponseRetry(): Promise<void> {
  const fixture = depsFrom([htmlResponse(), jsonResponse({ projects: [{ dir: "/recovered" }] })]);
  const projects = await loadProjects<TestProject>(new AbortController().signal, fixture.deps);
  assert.deepEqual(projects, [{ dir: "/recovered" }]);
  assert.equal(fixture.calls(), 2);
  assert.equal(fixture.delays(), 1);
}

async function testNetworkRetry(): Promise<void> {
  const fixture = depsFrom([new TypeError("network unavailable"), jsonResponse({ projects: [] })]);
  const projects = await loadProjects<TestProject>(new AbortController().signal, fixture.deps);
  assert.deepEqual(projects, []);
  assert.equal(fixture.calls(), 2);
}

async function testOpaqueErrorDoesNotLeak(): Promise<void> {
  const result = await expectClientError([htmlResponse(500), htmlResponse(500)]);
  assert.equal(result.calls, 2);
  assert.match(result.error.message, /unreadable response \(HTTP 500\)/);
  assert.doesNotMatch(result.error.message, /expected pattern/i);
}

async function testJsonErrorIsPreserved(): Promise<void> {
  const result = await expectClientError([jsonResponse({ error: "registry needs repair" }, 500)]);
  assert.equal(result.calls, 1);
  assert.equal(result.error.message, "registry needs repair");
}

async function testOpaqueJsonErrorIsSanitized(): Promise<void> {
  const opaque = { error: "The string did not match the expected pattern." };
  const result = await expectClientError([jsonResponse(opaque, 500), jsonResponse(opaque, 500)]);
  assert.equal(result.calls, 2);
  assert.doesNotMatch(result.error.message, /expected pattern/i);
  assert.match(result.error.message, /unreadable response/);
}

async function testMalformedJsonStopsAfterRetry(): Promise<void> {
  const malformed = () => new Response("{", { headers: { "content-type": "application/json" } });
  const result = await expectClientError([malformed(), malformed()]);
  assert.equal(result.calls, 2);
  assert.match(result.error.message, /unreadable response/);
}

async function testWrongShapeStopsAfterRetry(): Promise<void> {
  const result = await expectClientError([
    jsonResponse({ projects: "not-an-array" }),
    jsonResponse({ projects: "still-not-an-array" }),
  ]);
  assert.equal(result.calls, 2);
  assert.match(result.error.message, /unreadable response/);
}

async function testAbortDoesNotRetry(): Promise<void> {
  const controller = new AbortController();
  controller.abort(new DOMException("stopped", "AbortError"));
  const fixture = depsFrom([new DOMException("stopped", "AbortError")]);
  await assert.rejects(loadProjects<TestProject>(controller.signal, fixture.deps), /stopped/);
  assert.equal(fixture.calls(), 1);
  assert.equal(fixture.delays(), 0);
}

async function main(): Promise<void> {
  await testValidJson();
  await testTransientResponseRetry();
  await testNetworkRetry();
  await testOpaqueErrorDoesNotLeak();
  await testJsonErrorIsPreserved();
  await testOpaqueJsonErrorIsSanitized();
  await testMalformedJsonStopsAfterRetry();
  await testWrongShapeStopsAfterRetry();
  await testAbortDoesNotRetry();
  console.log("projects-client.test.ts: all assertions passed");
}

void main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
