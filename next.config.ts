import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // snowflake-sdk is a Node-only package; keep it out of the bundler.
  serverExternalPackages: ["snowflake-sdk"],
};

export default nextConfig;
