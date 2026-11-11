import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getHealth } from "@/lib/api";

import { HealthStatus } from "./HealthStatus";

vi.mock("@/lib/api");

describe("F-001 HealthStatus", () => {
  it("shows a checking state before the API answers", () => {
    vi.mocked(getHealth).mockReturnValue(new Promise(() => {}));

    render(<HealthStatus />);

    expect(screen.getByRole("status")).toHaveTextContent("API: checking…");
  });

  it("shows the status returned by /api/health", async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: "ok" });

    render(<HealthStatus />);

    expect(await screen.findByText("API: ok")).toBeInTheDocument();
  });

  it("shows the API as unreachable when the call fails", async () => {
    vi.mocked(getHealth).mockRejectedValue(new Error("network down"));

    render(<HealthStatus />);

    expect(await screen.findByText("API: unreachable")).toBeInTheDocument();
  });
});
