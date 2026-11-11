import { describe, expect, it, vi } from "vitest";

import { ApiError, getHealth } from "./api";

function stubFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("F-001 getHealth", () => {
  it("calls the same-origin /api/health path and returns the status", async () => {
    const fetchMock = stubFetch(Response.json({ status: "ok" }));

    await expect(getHealth()).resolves.toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });

  it("rejects with an ApiError when the backend responds with an error", async () => {
    stubFetch(new Response("bad gateway", { status: 502 }));

    const error = await getHealth().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(502);
  });
});
