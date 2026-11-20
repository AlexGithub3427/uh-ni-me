// The only place the frontend talks to the backend. Every call uses a
// same-origin /api/* path, which Next.js rewrites to the backend (API_URL).
// Responses are snake_case on the wire and mapped to camelCase here.

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: `/api/${string}`): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export interface Health {
  status: string;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export type RarityTier = "larp" | "normie" | "niche" | "weeb" | "uh-ni-me";

export interface PromptProgress {
  position: number;
  outcome: "accepted" | "expired";
  points: number;
  rarityTier: RarityTier | null;
}

export interface TodayPuzzle {
  /** UTC calendar date, YYYY-MM-DD. */
  day: string;
  promptCount: number;
  /** Finished prompts only, ordered by position. */
  progress: PromptProgress[];
}

interface TodayPuzzleWire {
  day: string;
  prompt_count: number;
  progress: {
    position: number;
    outcome: PromptProgress["outcome"];
    points: number;
    rarity_tier: RarityTier | null;
  }[];
}

/** Today's puzzle and the player's progress, or null when today has no puzzle. */
export async function getTodayPuzzle(): Promise<TodayPuzzle | null> {
  let wire: TodayPuzzleWire;
  try {
    wire = await getJson<TodayPuzzleWire>("/api/puzzle/today");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  return {
    day: wire.day,
    promptCount: wire.prompt_count,
    progress: wire.progress.map((entry) => ({
      position: entry.position,
      outcome: entry.outcome,
      points: entry.points,
      rarityTier: entry.rarity_tier,
    })),
  };
}

// TODO(F-041): add the POST helper and the start, answer and result calls.
