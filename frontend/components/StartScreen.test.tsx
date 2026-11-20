import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, getTodayPuzzle, type PromptProgress } from "@/lib/api";

import { StartScreen } from "./StartScreen";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getTodayPuzzle: vi.fn(),
}));

function finished(count: number): PromptProgress[] {
  return Array.from({ length: count }, (_, i) => ({
    position: i + 1,
    outcome: "accepted",
    points: 30,
    rarityTier: "normie",
  }));
}

function mockPuzzle(finishedCount: number) {
  vi.mocked(getTodayPuzzle).mockResolvedValue({
    day: "2026-11-16",
    promptCount: 7,
    progress: finished(finishedCount),
  });
}

describe("F-040 StartScreen", () => {
  it("shows a loading state before the API answers", () => {
    vi.mocked(getTodayPuzzle).mockReturnValue(new Promise(() => {}));

    render(<StartScreen />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading today's puzzle…");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows today's puzzle date from the API", async () => {
    mockPuzzle(0);

    render(<StartScreen />);

    const date = await screen.findByText("Monday, November 16, 2026");
    expect(date).toHaveAttribute("datetime", "2026-11-16");
  });

  it("shows the puzzle's UTC date whatever the player's time zone", async () => {
    // 2026-01-01 UTC is still December 31 in every time zone west of UTC.
    vi.stubEnv("TZ", "America/Los_Angeles");
    vi.mocked(getTodayPuzzle).mockResolvedValue({
      day: "2026-01-01",
      promptCount: 7,
      progress: [],
    });

    render(<StartScreen />);

    expect(await screen.findByText("Thursday, January 1, 2026")).toBeInTheDocument();
  });

  it("links Start to prompt 1 when nothing is played yet", async () => {
    mockPuzzle(0);

    render(<StartScreen />);

    const start = await screen.findByRole("link", { name: "Start" });
    expect(start).toHaveAttribute("href", "/play/2026-11-16/1");
  });

  it("resumes a partly played day at the first unfinished prompt", async () => {
    mockPuzzle(3);

    render(<StartScreen />);

    const resume = await screen.findByRole("link", { name: "Continue" });
    expect(resume).toHaveAttribute("href", "/play/2026-11-16/4");
    expect(screen.getByText("Prompt 4 of 7")).toBeInTheDocument();
  });

  it("shows come back tomorrow with a link to results when every prompt is finished", async () => {
    mockPuzzle(7);

    render(<StartScreen />);

    expect(await screen.findByText(/come back tomorrow/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See your results" })).toHaveAttribute(
      "href",
      "/play/2026-11-16/results",
    );
    expect(screen.queryByRole("link", { name: /start|continue/i })).not.toBeInTheDocument();
  });

  it("shows a friendly no-puzzle state when today has no puzzle", async () => {
    vi.mocked(getTodayPuzzle).mockResolvedValue(null);

    render(<StartScreen />);

    expect(await screen.findByText("No puzzle yet")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error with a retry when the API can't be reached", async () => {
    vi.mocked(getTodayPuzzle).mockRejectedValue(new ApiError(502, "bad gateway"));

    render(<StartScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load today's puzzle");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("loads the puzzle again when Try again is pressed", async () => {
    vi.mocked(getTodayPuzzle).mockRejectedValueOnce(new ApiError(502, "bad gateway"));
    mockPuzzle(0);

    render(<StartScreen />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("link", { name: "Start" })).toBeInTheDocument();
    expect(getTodayPuzzle).toHaveBeenCalledTimes(2);
  });
});
