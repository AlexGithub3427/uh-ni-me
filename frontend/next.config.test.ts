import { describe, expect, it, vi } from "vitest";

import nextConfig from "./next.config";

describe("F-001 /api rewrite", () => {
  it("proxies /api/* to the backend at API_URL", async () => {
    vi.stubEnv("API_URL", "http://backend.internal:9000");

    expect(await nextConfig.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "http://backend.internal:9000/api/:path*" },
    ]);
  });

  it("defaults to the local backend when API_URL is unset", async () => {
    vi.stubEnv("API_URL", undefined);

    expect(await nextConfig.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
    ]);
  });
});
