const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// Existing GUI calls with no request body. Every other mutation must declare
// application/json so a cross-site "simple" text/plain POST cannot reach a
// route merely because that route calls request.json().
const BODYLESS_MUTATIONS = new Set([
  "POST /api/frameio-review/pick-file",
  "DELETE /api/producer/projects",
  "DELETE /api/producer/references",
]);

interface RequestPolicyInput {
  method: string;
  pathname: string;
  protocol: string;
  host: string | null;
  origin: string | null;
  secFetchSite: string | null;
  contentType: string | null;
}

export interface PolicyRejection {
  status: 403 | 415;
  error: string;
}

function parseAuthority(protocol: string, host: string | null): URL | null {
  if (!host || (protocol !== "http:" && protocol !== "https:")) return null;
  try {
    const url = new URL(`${protocol}//${host.trim()}`);
    const invalid =
      url.username !== "" ||
      url.password !== "" ||
      url.pathname !== "/" ||
      url.search !== "" ||
      url.hash !== "";
    return invalid ? null : url;
  } catch {
    return null;
  }
}

function normalizedHostname(hostname: string): string {
  const unwrapped = hostname.startsWith("[") ? hostname.slice(1, -1) : hostname;
  return unwrapped.toLowerCase().replace(/\.$/, "");
}

/** True only for a literal localhost, IPv4 loopback, or IPv6 loopback Host. */
export function isLoopbackHost(host: string | null): boolean {
  const authority = parseAuthority("http:", host);
  if (!authority) return false;
  const name = normalizedHostname(authority.hostname);
  return name === "localhost" || name === "127.0.0.1" || name === "::1";
}

/** A present Origin must exactly match the request scheme, host, and port. */
export function isSameOrigin(
  origin: string | null,
  protocol: string,
  host: string | null,
): boolean {
  if (!origin) return true;
  const expected = parseAuthority(protocol, host);
  if (!expected || origin === "null") return false;
  try {
    const actual = new URL(origin);
    const invalid =
      actual.username !== "" ||
      actual.password !== "" ||
      actual.pathname !== "/" ||
      actual.search !== "" ||
      actual.hash !== "";
    return !invalid && actual.origin === expected.origin;
  } catch {
    return false;
  }
}

function normalizedPathname(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function requiresJsonContentType(method: string, pathname: string): boolean {
  const verb = method.toUpperCase();
  if (!MUTATING_METHODS.has(verb)) return false;
  return !BODYLESS_MUTATIONS.has(`${verb} ${normalizedPathname(pathname)}`);
}

export function hasJsonContentType(contentType: string | null): boolean {
  return contentType?.split(";", 1)[0].trim().toLowerCase() === "application/json";
}

/** Return the local-mode rejection, or null when the API request may proceed. */
export function localApiRejection(input: RequestPolicyInput): PolicyRejection | null {
  if (!isLoopbackHost(input.host)) {
    return { status: 403, error: "Local mode accepts only loopback Host headers" };
  }
  if (input.secFetchSite?.toLowerCase() === "cross-site") {
    return { status: 403, error: "Cross-site API requests are forbidden in local mode" };
  }
  if (!isSameOrigin(input.origin, input.protocol, input.host)) {
    return { status: 403, error: "API Origin must match the local Sniper origin" };
  }
  const needsJson = requiresJsonContentType(input.method, input.pathname);
  if (needsJson && !hasJsonContentType(input.contentType)) {
    return { status: 415, error: "Mutating API requests require application/json" };
  }
  return null;
}
