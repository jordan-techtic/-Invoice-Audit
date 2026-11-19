import type { NextConfig } from "next";

const apiUrl = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // Invoice uploads go through the /api proxy; allow the 25 MB limit shown in the UI.
    proxyClientMaxBodySize: "30mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
