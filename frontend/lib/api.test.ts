import { describe, expect, it, vi } from "vitest";

import { ApiError, getHealth, getTodayPuzzle } from "./api";

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

describe("F-040 getTodayPuzzle", () => {
  it("calls /api/puzzle/today and maps the response to camelCase", async () => {
    const fetchMock = stubFetch(
      Response.json({
        day: "2026-11-16",
        prompt_count: 7,
        progress: [
          { position: 1, outcome: "accepted", points: 60, rarity_tier: "niche" },
          { position: 2, outcome: "expired", points: 0, rarity_tier: null },
        ],
      }),
    );

    await expect(getTodayPuzzle()).resolves.toEqual({
      day: "2026-11-16",
      promptCount: 7,
      progress: [
        { position: 1, outcome: "accepted", points: 60, rarityTier: "niche" },
        { position: 2, outcome: "expired", points: 0, rarityTier: null },
      ],
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/puzzle/today");
  });

  it("resolves to null when there is no puzzle for today (404)", async () => {
    stubFetch(Response.json({ detail: "No puzzle for today" }, { status: 404 }));

    await expect(getTodayPuzzle()).resolves.toBeNull();
  });

  it("rejects with an ApiError for any other error status", async () => {
    stubFetch(new Response("boom", { status: 500 }));

    const error = await getTodayPuzzle().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(500);
  });
});
