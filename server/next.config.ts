import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The SQLite file is data, not code, so tracing has to be told about it.
  outputFileTracingIncludes: {
    "/**": ["./data/vanre.db"],
  },
};

export default nextConfig;
