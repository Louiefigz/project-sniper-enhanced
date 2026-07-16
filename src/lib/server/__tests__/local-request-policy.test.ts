import assert from "node:assert/strict";
import {
  hasJsonContentType,
  isLoopbackHost,
  isSameOrigin,
  localApiRejection,
  requiresJsonContentType,
} from "../local-request-policy";

// Literal loopback authorities are accepted, including ports and IPv6 syntax.
for (const host of ["localhost", "LOCALHOST:3000", "localhost.:3000", "127.0.0.1:3000", "[::1]:3000"]) {
  assert.equal(isLoopbackHost(host), true, `expected loopback Host: ${host}`);
}

// Remote names, malformed authorities, and loopback-looking suffixes fail.
for (const host of [
  null,
  "",
  "example.com:3000",
  "localhost.example.com",
  "127.0.0.2",
  "[::2]:3000",
  "localhost:bad",
  "evil.test@localhost:3000",
  "localhost:3000/path",
]) {
  assert.equal(isLoopbackHost(host), false, `expected forbidden Host: ${host}`);
}

// Origin comparison is scheme + host + port exact; absent Origin supports curl.
assert.equal(isSameOrigin(null, "http:", "localhost:3000"), true);
assert.equal(isSameOrigin("http://localhost:3000", "http:", "localhost:3000"), true);
assert.equal(isSameOrigin("http://127.0.0.1:3000", "http:", "127.0.0.1:3000"), true);
assert.equal(isSameOrigin("http://[::1]:3000", "http:", "[::1]:3000"), true);
assert.equal(isSameOrigin("https://localhost:3000", "http:", "localhost:3000"), false);
assert.equal(isSameOrigin("http://localhost:4000", "http:", "localhost:3000"), false);
assert.equal(isSameOrigin("http://127.0.0.1:3000", "http:", "localhost:3000"), false);
assert.equal(isSameOrigin("null", "http:", "localhost:3000"), false);
assert.equal(isSameOrigin("http://localhost:3000/path", "http:", "localhost:3000"), false);

assert.equal(hasJsonContentType("application/json"), true);
assert.equal(hasJsonContentType("Application/JSON; charset=utf-8"), true);
assert.equal(hasJsonContentType("text/plain"), false);
assert.equal(hasJsonContentType(null), false);

assert.equal(requiresJsonContentType("POST", "/api/producer/render"), true);
assert.equal(requiresJsonContentType("POST", "/api/producer/auto-edit/stop"), true);
assert.equal(requiresJsonContentType("DELETE", "/api/producer/projects"), false);
assert.equal(requiresJsonContentType("DELETE", "/api/producer/references/"), false);
assert.equal(requiresJsonContentType("POST", "/api/frameio-review/pick-file"), false);
assert.equal(requiresJsonContentType("GET", "/api/producer/projects"), false);

const base = {
  method: "POST",
  pathname: "/api/producer/render",
  protocol: "http:",
  host: "localhost:3000",
  origin: "http://localhost:3000",
  secFetchSite: "same-origin",
  contentType: "application/json",
};

assert.equal(localApiRejection(base), null);
assert.equal(localApiRejection({ ...base, host: "sniper.example" })?.status, 403);
assert.equal(localApiRejection({ ...base, origin: "http://evil.example" })?.status, 403);
assert.equal(localApiRejection({ ...base, secFetchSite: "cross-site" })?.status, 403);
assert.equal(localApiRejection({ ...base, contentType: "text/plain" })?.status, 415);
assert.equal(
  localApiRejection({
    ...base,
    pathname: "/api/frameio-review/pick-file",
    origin: null,
    secFetchSite: null,
    contentType: null,
  }),
  null,
);

console.log("local-request-policy.test.ts: all assertions passed");
