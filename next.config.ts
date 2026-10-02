import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // snowflake-sdk is a Node-only package; keep it out of the bundler.
  serverExternalPackages: ["snowflake-sdk"],
  // The weekly dashboard is read from disk by app/route.ts; include it in the server bundle.
  outputFileTracingIncludes: {
    "/": ["./dashboard/**"],
  },
};

export default nextConfig;
