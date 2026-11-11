import type { NextConfig } from "next";

const DEFAULT_API_URL = "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // The browser only calls same-origin /api/* paths; Next.js proxies them to
  // the backend. API_URL is server-side only and is read when the server
  // starts (`next dev`) or when the app is built (`next build`).
  async rewrites() {
    const apiUrl = (process.env.API_URL ?? DEFAULT_API_URL).replace(/\/+$/, "");
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
