import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ValidAnswer } from "@/lib/api";

import { AnswerBrowser } from "./AnswerBrowser";

const answers: ValidAnswer[] = [
  { name: "Chainsaw Man", rarityTier: "normie" },
  { name: "Dorohedoro", rarityTier: "weeb" },
  { name: "Jujutsu Kaisen", rarityTier: "larp" },
  { name: "Kakegurui", rarityTier: "niche" },
  { name: "Shingeki no Kyojin: The Final Season", rarityTier: "larp" },
  { name: "Zombieland Saga", rarityTier: "niche" },
  { name: "Kyōsōgiga", rarityTier: "uh-ni-me" },
];

function listedNames(): string[] {
  const list = screen.getByRole("list", { name: "Valid answers" });
  return within(list)
    .queryAllByRole("listitem")
    .map((item) => item.querySelector("[data-answer-name]")?.textContent ?? "");
}

describe("F-041 AnswerBrowser", () => {
  it("lists every valid answer in the order given (alphabetical from the server) with its tier", () => {
    render(<AnswerBrowser answers={answers} />);

    expect(listedNames()).toEqual(answers.map((a) => a.name));
    const dorohedoro = screen.getByText("Dorohedoro").closest("li")!;
    expect(dorohedoro).toHaveTextContent("weeb");
    expect(screen.getByText("7 of 7 answers")).toBeInTheDocument();
  });

  it("filters by a case-insensitive search", () => {
    render(<AnswerBrowser answers={answers} />);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search answers" }), {
      target: { value: "KAI" },
    });

    expect(listedNames()).toEqual(["Jujutsu Kaisen"]);
    expect(screen.getByText("1 of 7 answers")).toBeInTheDocument();
  });

  it("ignores macrons and accents in the search", () => {
    render(<AnswerBrowser answers={answers} />);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search answers" }), {
      target: { value: "kyoso" },
    });

    expect(listedNames()).toEqual(["Kyōsōgiga"]);
  });

  it("filters by rarity tier", () => {
    render(<AnswerBrowser answers={answers} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Rarity" }), {
      target: { value: "niche" },
    });

    expect(listedNames()).toEqual(["Kakegurui", "Zombieland Saga"]);
  });

  it("combines search and tier filter", () => {
    render(<AnswerBrowser answers={answers} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Rarity" }), {
      target: { value: "larp" },
    });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search answers" }), {
      target: { value: "shingeki" },
    });

    expect(listedNames()).toEqual(["Shingeki no Kyojin: The Final Season"]);
  });

  it("says so when nothing matches", () => {
    render(<AnswerBrowser answers={answers} />);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search answers" }), {
      target: { value: "one piece" },
    });

    expect(listedNames()).toEqual([]);
    expect(screen.getByText("No answers match.")).toBeInTheDocument();
  });
});
