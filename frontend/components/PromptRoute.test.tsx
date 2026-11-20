import { isValidElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { viewport } from "@/app/play/[day]/[n]/page";

import { PromptRoute } from "./PromptRoute";
import { PromptScreen } from "./PromptScreen";

class NotFound extends Error {}

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new NotFound();
  },
  useRouter: () => ({ replace: vi.fn() }),
}));

function route(day: string, n: string) {
  return PromptRoute({ params: Promise.resolve({ day, n }) });
}

describe("F-041 prompt route", () => {
  it("renders the prompt screen for /play/{day}/{n}, keyed so each prompt starts fresh", async () => {
    const element = await route("2026-11-16", "3");

    expect(isValidElement(element)).toBe(true);
    expect(element.type).toBe(PromptScreen);
    expect(element.props).toEqual({ day: "2026-11-16", position: 3 });
    expect(element.key).toBe("2026-11-16/3");
  });

  it.each(["0", "-1", "1.5", "abc", "results", "01x"])("is a 404 for n = %s", async (n) => {
    await expect(route("2026-11-16", n)).rejects.toBeInstanceOf(NotFound);
  });

  it("lets the on-screen keyboard resize the page, so the input stays above it", () => {
    expect(viewport.interactiveWidget).toBe("resizes-content");
  });
});
