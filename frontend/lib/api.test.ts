import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getHealth,
  getPromptResult,
  getTodayPuzzle,
  startPrompt,
  submitGuess,
} from "./api";

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

describe("F-041 startPrompt", () => {
  it("posts to the start path and maps the response to camelCase", async () => {
    const fetchMock = stubFetch(
      Response.json({
        position: 2,
        text: "Name an anime by MAPPA",
        started_at: "2026-11-16T12:00:00Z",
        deadline: "2026-11-16T12:00:25Z",
        now: "2026-11-16T12:00:03Z",
      }),
    );

    await expect(startPrompt("2026-11-16", 2)).resolves.toEqual({
      position: 2,
      text: "Name an anime by MAPPA",
      startedAt: "2026-11-16T12:00:00Z",
      deadline: "2026-11-16T12:00:25Z",
      now: "2026-11-16T12:00:03Z",
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/play/2026-11-16/prompt/2/start");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
  });

  it("rejects with an ApiError carrying the status", async () => {
    stubFetch(Response.json({ detail: "Previous prompt not finished" }, { status: 409 }));

    const error = await startPrompt("2026-11-16", 3).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
  });
});

describe("F-041 submitGuess", () => {
  it("posts the text as JSON and maps the response to camelCase", async () => {
    const fetchMock = stubFetch(
      Response.json({
        accepted: true,
        finished: true,
        matched_name: "Jujutsu Kaisen",
        points: 30,
        rarity_tier: "normie",
      }),
    );

    await expect(submitGuess("2026-11-16", 1, "jjk")).resolves.toEqual({
      accepted: true,
      finished: true,
      matchedName: "Jujutsu Kaisen",
      points: 30,
      rarityTier: "normie",
    });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/play/2026-11-16/prompt/1/answer");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init?.body as string)).toEqual({ text: "jjk" });
  });

  it("rejects with an ApiError when the player is out of guesses (429)", async () => {
    stubFetch(Response.json({ detail: "Too many guesses" }, { status: 429 }));

    const error = await submitGuess("2026-11-16", 1, "x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(429);
  });
});

describe("F-041 getPromptResult", () => {
  it("gets the result path and maps the response to camelCase", async () => {
    const fetchMock = stubFetch(
      Response.json({
        outcome: "accepted",
        matched_name: "Chainsaw Man",
        points: 60,
        rarity_tier: "niche",
        answers: [
          { name: "Chainsaw Man", rarity_tier: "niche" },
          { name: "Jujutsu Kaisen", rarity_tier: "larp" },
        ],
      }),
    );

    await expect(getPromptResult("2026-11-16", 4)).resolves.toEqual({
      outcome: "accepted",
      matchedName: "Chainsaw Man",
      points: 60,
      rarityTier: "niche",
      answers: [
        { name: "Chainsaw Man", rarityTier: "niche" },
        { name: "Jujutsu Kaisen", rarityTier: "larp" },
      ],
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/play/2026-11-16/prompt/4/result");
  });

  it("rejects with an ApiError while the prompt is still being played (409)", async () => {
    stubFetch(Response.json({ detail: "Prompt not finished" }, { status: 409 }));

    const error = await getPromptResult("2026-11-16", 4).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
  });
});
