import type { NextConfig } from "next";

const apiUrl = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  experimental: {
    // Invoice uploads go through the /api proxy; allow the 25 MB limit shown in the UI.
    proxyClientMaxBodySize: "30mb",
    // The /api proxy gives up after 30 s by default and answers 500 ("The server hit a problem").
    // With QUEUE_INLINE=true the backend reads uploads and runs checks inside the request (OpenAI calls),
    // which often takes longer. Allow as long as a backend job may run (job_timeout=900 in api/app/queue.py).
    proxyTimeout: 900_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
