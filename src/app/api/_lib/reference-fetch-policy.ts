const ALLOWED_ROOTS = ["youtube.com", "youtu.be", "instagram.com", "tiktok.com"] as const;

function matchesRoot(hostname: string, root: string): boolean {
  return hostname === root || hostname.endsWith(`.${root}`);
}

export function parseReferenceUrl(raw: string): URL {
  if (raw.length > 2048) throw new Error("reference URL is too long");
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`not a valid URL: ${raw}`);
  }
  if (url.protocol !== "https:") {
    throw new Error(`reference URLs must use https (got ${url.protocol})`);
  }
  if (url.username || url.password) throw new Error("reference URL must not contain credentials");
  const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
  if (!ALLOWED_ROOTS.some((root) => matchesRoot(hostname, root))) {
    throw new Error("reference URL host must be YouTube, Instagram, or TikTok");
  }
  if (url.port && url.port !== "80" && url.port !== "443") {
    throw new Error("reference URL may not use a non-standard port");
  }
  return url;
}
