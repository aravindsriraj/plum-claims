import type { NextConfig } from "next";

const apiUrl = process.env.API_URL ?? "http://localhost:8080";

const nextConfig: NextConfig = {
  output: "standalone",
  // Browser calls /api/* on this service; Next proxies to the backend.
  // Keeps the backend URL server-side only (no CORS, no exposed config).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
