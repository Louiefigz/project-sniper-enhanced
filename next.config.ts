import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
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
  allowedDevOrigins: ["julians-mac-mini.tail8538b4.ts.net"],
};

export default nextConfig;
