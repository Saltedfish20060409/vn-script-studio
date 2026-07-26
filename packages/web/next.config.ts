import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@vnss/core"],
  webpack: (config) => {
    // Allow TS sources that import with ESM ".js" extensions (NodeNext style).
    config.resolve.extensionAlias = {
      ".js": [".ts", ".tsx", ".js", ".jsx"],
      ".mjs": [".mts", ".mjs"],
    };
    return config;
  },
};

export default nextConfig;
