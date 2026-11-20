import { notFound } from "next/navigation";

import { PromptScreen } from "./PromptScreen";

/**
 * Reads the `/play/{day}/{n}` params and renders that prompt. Anything but a
 * positive integer `n` is a 404. A bad or past `day` is left to the API, which
 * answers 404, and the prompt screen then sends the player home.
 */
export async function PromptRoute({ params }: { params: Promise<{ day: string; n: string }> }) {
  const { day, n } = await params;
  if (!/^[1-9]\d*$/.test(n)) notFound();
  const position = Number(n);
  // Keyed so moving to the next prompt starts with fresh state.
  return <PromptScreen key={`${day}/${position}`} day={day} position={position} />;
}
