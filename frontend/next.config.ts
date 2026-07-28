import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Browser calls /api/*; app/api/[...path] proxies to API_URL at runtime
  // (Cloud Run / compose set API_URL as an env var — no rebuild needed).
};

export default nextConfig;
