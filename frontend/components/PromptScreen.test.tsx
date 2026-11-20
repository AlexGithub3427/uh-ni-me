import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getPromptResult,
  getTodayPuzzle,
  startPrompt,
  submitGuess,
  type PromptResult,
  type StartedPrompt,
} from "@/lib/api";

import { PromptScreen } from "./PromptScreen";

const replace = vi.fn();

// Like Next's, the router object is stable across renders.
vi.mock("next/navigation", () => {
  const router = { replace: (href: string) => replace(href), push: vi.fn() };
  return { useRouter: () => router };
});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getTodayPuzzle: vi.fn(),
  startPrompt: vi.fn(),
  submitGuess: vi.fn(),
  getPromptResult: vi.fn(),
}));

const DAY = "2026-11-16";

/** A start response whose server clock says `secondsLeft` remain. */
function started(secondsLeft: number, position = 2): StartedPrompt {
  const deadline = Date.parse("2026-11-16T12:00:25Z");
  return {
    position,
    text: "Name an anime by MAPPA",
    startedAt: "2026-11-16T12:00:00Z",
    deadline: new Date(deadline).toISOString(),
    now: new Date(deadline - secondsLeft * 1000).toISOString(),
  };
}

const acceptedResult: PromptResult = {
  outcome: "accepted",
  matchedName: "Chainsaw Man",
  points: 60,
  rarityTier: "niche",
  answers: [
    { name: "Chainsaw Man", rarityTier: "niche" },
    { name: "Dorohedoro", rarityTier: "weeb" },
    { name: "Jujutsu Kaisen", rarityTier: "larp" },
  ],
};

const expiredResult: PromptResult = {
  outcome: "expired",
  matchedName: null,
  points: 0,
  rarityTier: null,
  answers: acceptedResult.answers,
};

const wrong = { accepted: false, finished: false, matchedName: null, points: 0, rarityTier: null };

/** Let pending promises settle and run timers due within `ms`. */
async function advance(ms = 0) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

function input() {
  return screen.getByRole("textbox", { name: "Your answer" });
}

function guess(text: string) {
  fireEvent.change(input(), { target: { value: text } });
  fireEvent.submit(input().closest("form")!);
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
  });
  replace.mockReset();
  vi.mocked(getTodayPuzzle).mockResolvedValue({ day: DAY, promptCount: 7, progress: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("F-041 PromptScreen countdown", () => {
  it("starts the prompt and shows its text with an autofocused input", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(startPrompt).toHaveBeenCalledWith(DAY, 2);
    expect(screen.getByRole("heading", { name: "Name an anime by MAPPA" })).toBeInTheDocument();
    expect(input()).toHaveFocus();
    expect(screen.getByText("Prompt 2 of 7")).toBeInTheDocument();
  });

  it("counts down from deadline − now of the start response, not the player's clock", async () => {
    // The player's clock is years off; only the server's deadline − now counts.
    vi.setSystemTime(new Date("2031-05-05T08:00:00Z"));
    vi.mocked(startPrompt).mockResolvedValue(started(20));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(screen.getByRole("timer")).toHaveTextContent("20");
    await advance(5000);
    expect(screen.getByRole("timer")).toHaveTextContent("15");
  });

  it("counts from when the response arrived, so request latency doesn't eat the time", async () => {
    let resolve!: (value: StartedPrompt) => void;
    vi.mocked(startPrompt).mockReturnValue(new Promise((r) => (resolve = r)));

    render(<PromptScreen day={DAY} position={2} />);
    await advance(3000); // a slow request
    resolve(started(25));
    await advance();

    expect(screen.getByRole("timer")).toHaveTextContent("25");
  });

  it("fetches the result when the countdown runs out, retrying on 409 during the grace period", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(5));
    vi.mocked(getPromptResult)
      .mockRejectedValueOnce(new ApiError(409, "not finished"))
      .mockRejectedValueOnce(new ApiError(409, "not finished"))
      .mockResolvedValue(expiredResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    expect(getPromptResult).not.toHaveBeenCalled();

    await advance(5000);
    expect(screen.getByText("Time's up")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
    expect(getPromptResult).toHaveBeenCalledTimes(1);

    await advance(2000);
    expect(getPromptResult).toHaveBeenCalledTimes(3);
    expect(screen.getByText("0 points")).toBeInTheDocument();
  });

  it("goes straight to the result when resuming a prompt whose time already ran out", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(-40));
    vi.mocked(getPromptResult).mockResolvedValue(expiredResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(screen.queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
    expect(screen.getByText("Time's up")).toBeInTheDocument();
    expect(screen.getByText("0 points")).toBeInTheDocument();
  });
});

describe("F-041 PromptScreen guesses", () => {
  it("shows brief feedback for a wrong guess, clears the input and keeps it focused", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockResolvedValue(wrong);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();

    expect(submitGuess).toHaveBeenCalledWith(DAY, 2, "naruto");
    expect(screen.getByRole("status")).toHaveTextContent("Not a valid answer");
    expect(input()).toHaveValue("");
    expect(input()).toHaveFocus();
    expect(input()).toBeEnabled();

    await advance(3000);
    expect(screen.getByRole("status")).not.toHaveTextContent("Not a valid answer");
  });

  it("lets the player retry after a wrong guess", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockResolvedValueOnce(wrong).mockResolvedValueOnce(wrong);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();
    guess("bleach");
    await advance();

    expect(submitGuess).toHaveBeenCalledTimes(2);
    expect(submitGuess).toHaveBeenLastCalledWith(DAY, 2, "bleach");
  });

  it("doesn't send a blank guess", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("   ");
    await advance();

    expect(submitGuess).not.toHaveBeenCalled();
  });

  it("stops taking guesses on 429 and waits for the timer", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(10));
    vi.mocked(submitGuess).mockRejectedValue(new ApiError(429, "too many"));
    vi.mocked(getPromptResult).mockResolvedValue(expiredResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();

    expect(input()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/out of guesses/i);
    expect(getPromptResult).not.toHaveBeenCalled();

    await advance(10000);
    expect(getPromptResult).toHaveBeenCalled();
  });

  it("keeps the text and says so when a guess can't be sent", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockRejectedValue(new TypeError("network down"));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();

    expect(screen.getByRole("status")).toHaveTextContent(/couldn't send/i);
    expect(input()).toHaveValue("naruto");
  });
});

describe("F-041 PromptScreen finished state", () => {
  it("shows the accepted answer, points, tier, the answer browser and a Next link", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockResolvedValue({
      accepted: true,
      finished: true,
      matchedName: "Chainsaw Man",
      points: 60,
      rarityTier: "niche",
    });
    vi.mocked(getPromptResult).mockResolvedValue(acceptedResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("csm");
    await advance();

    expect(getPromptResult).toHaveBeenCalledWith(DAY, 2);
    expect(
      screen.getByText("Chainsaw Man", { selector: "[data-matched-name]" }),
    ).toBeInTheDocument();
    expect(screen.getByText("+60 points")).toBeInTheDocument();
    expect(screen.getByText("niche", { selector: "[data-player-tier]" })).toBeInTheDocument();
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Valid answers" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute("href", `/play/${DAY}/3`);
  });

  it("shows time's up with no points when the guess response says the prompt expired", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(1));
    vi.mocked(submitGuess).mockResolvedValue({ ...wrong, finished: true });
    vi.mocked(getPromptResult).mockResolvedValue(expiredResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();

    expect(screen.getByText("Time's up")).toBeInTheDocument();
    expect(screen.getByText("0 points")).toBeInTheDocument();
  });

  it("links the last prompt to the results screen", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(-40, 7));
    vi.mocked(getPromptResult).mockResolvedValue(expiredResult);

    render(<PromptScreen day={DAY} position={7} />);
    await advance();

    expect(screen.getByRole("link", { name: "See your results" })).toHaveAttribute(
      "href",
      `/play/${DAY}/results`,
    );
  });

  it("shows the result when the answer endpoint says the prompt was already answered (409)", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockRejectedValue(new ApiError(409, "already answered"));
    vi.mocked(getPromptResult).mockResolvedValue(acceptedResult);

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("csm");
    await advance();

    expect(screen.getByText("+60 points")).toBeInTheDocument();
  });
});

describe("F-041 PromptScreen navigation and errors", () => {
  it("sends the player home when the day is no longer today (404 on start)", async () => {
    vi.mocked(startPrompt).mockRejectedValue(new ApiError(404, "not today"));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(replace).toHaveBeenCalledWith("/");
  });

  it("sends the player home when the day rolls over mid-prompt (404 on a guess)", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));
    vi.mocked(submitGuess).mockRejectedValue(new ApiError(404, "not today"));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    guess("naruto");
    await advance();

    expect(replace).toHaveBeenCalledWith("/");
  });

  it("sends the player home when the result endpoint answers 404", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(-40));
    vi.mocked(getPromptResult).mockRejectedValue(new ApiError(404, "not today"));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(replace).toHaveBeenCalledWith("/");
  });

  it("sends the player home when an earlier prompt isn't finished (409 on start)", async () => {
    vi.mocked(startPrompt).mockRejectedValue(new ApiError(409, "previous not finished"));

    render(<PromptScreen day={DAY} position={4} />);
    await advance();

    expect(replace).toHaveBeenCalledWith("/");
  });

  it("shows an error with a retry when the prompt can't be loaded", async () => {
    vi.mocked(startPrompt)
      .mockRejectedValueOnce(new ApiError(502, "bad gateway"))
      .mockResolvedValue(started(25));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load this prompt");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await advance();
    expect(screen.getByRole("heading", { name: "Name an anime by MAPPA" })).toBeInTheDocument();
  });
});

describe("F-041 PromptScreen on mobile", () => {
  it("uses an input that suits on-screen keyboards", async () => {
    vi.mocked(startPrompt).mockResolvedValue(started(25));

    render(<PromptScreen day={DAY} position={2} />);
    await advance();

    expect(input()).toHaveAttribute("enterkeyhint", "send");
    expect(input()).toHaveAttribute("autocomplete", "off");
    expect(input()).toHaveAttribute("autocapitalize", "off");
    expect(input()).toHaveAttribute("spellcheck", "false");
  });
});
