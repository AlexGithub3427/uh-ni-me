import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getTodayPuzzle } from "@/lib/api";

import Home from "./page";

vi.mock("@/lib/api");

describe("F-040 home page", () => {
  it("shows the title, a short how to play and the start screen", () => {
    vi.mocked(getTodayPuzzle).mockReturnValue(new Promise(() => {}));

    render(<Home />);

    expect(screen.getByRole("heading", { level: 1, name: "UH-NI-ME" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "How to play" })).toBeInTheDocument();
    const howToPlay = screen.getByRole("region", { name: "How to play" });
    expect(within(howToPlay).getByText(/25 seconds per prompt/)).toBeInTheDocument();
    expect(within(howToPlay).getByText(/rarer your answer/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading today's puzzle…");
  });
});
