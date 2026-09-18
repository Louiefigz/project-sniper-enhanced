import type { NextConfig } from "next";
import path from "path";

// Isolated qualification servers must not rebuild an already-running editor's .next.
// Only a local sibling cache name is accepted; no arbitrary output-directory traversal.
const qualificationDist = process.env.SNIPER_NEXT_DIST_DIR;
if (qualificationDist && !/^\.next-[a-z0-9-]{1,64}$/.test(qualificationDist)) {
  throw new Error("SNIPER_NEXT_DIST_DIR must be a .next-<lowercase-slug> cache directory");
}

const nextConfig: NextConfig = {
  ...(qualificationDist ? { distDir: qualificationDist } : {}),
  turbopack: {
    root: path.resolve(__dirname),
  },
  experimental: {
    serverActions: {
      bodySizeLimit: "500mb",
    },
  },
  httpAgentOptions: {
    keepAlive: true,
  },
};

export default nextConfig;
