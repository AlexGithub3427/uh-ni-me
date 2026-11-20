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

async function postJson<T>(path: `/api/${string}`, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method: "POST", headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new ApiError(response.status, `POST ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export interface Health {
  status: string;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

/** Rarity tiers from most common to rarest (F-033). */
export const RARITY_TIERS = ["larp", "normie", "niche", "weeb", "uh-ni-me"] as const;

export type RarityTier = (typeof RARITY_TIERS)[number];

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

function promptPath(day: string, position: number, action: string): `/api/${string}` {
  return `/api/play/${encodeURIComponent(day)}/prompt/${position}/${action}`;
}

export interface StartedPrompt {
  position: number;
  text: string;
  /** Server times (ISO 8601). `deadline` excludes the grace period. */
  startedAt: string;
  deadline: string;
  /** The server's time when it answered. Time left is `deadline` − `now`. */
  now: string;
}

interface StartedPromptWire {
  position: number;
  text: string;
  started_at: string;
  deadline: string;
  now: string;
}

/**
 * Serve prompt `position` of `day` and start its timer, or resume it with the
 * original start time. Creates the player cookie on the first start.
 */
export async function startPrompt(day: string, position: number): Promise<StartedPrompt> {
  const wire = await postJson<StartedPromptWire>(promptPath(day, position, "start"));
  return {
    position: wire.position,
    text: wire.text,
    startedAt: wire.started_at,
    deadline: wire.deadline,
    now: wire.now,
  };
}

export interface GuessResult {
  accepted: boolean;
  /** `finished` without `accepted` means the prompt ran out of time. */
  finished: boolean;
  matchedName: string | null;
  points: number;
  rarityTier: RarityTier | null;
}

interface GuessResultWire {
  accepted: boolean;
  finished: boolean;
  matched_name: string | null;
  points: number;
  rarity_tier: RarityTier | null;
}

export async function submitGuess(
  day: string,
  position: number,
  text: string,
): Promise<GuessResult> {
  const wire = await postJson<GuessResultWire>(promptPath(day, position, "answer"), { text });
  return {
    accepted: wire.accepted,
    finished: wire.finished,
    matchedName: wire.matched_name,
    points: wire.points,
    rarityTier: wire.rarity_tier,
  };
}

export interface ValidAnswer {
  name: string;
  rarityTier: RarityTier;
}

export interface PromptResult {
  outcome: "accepted" | "expired";
  matchedName: string | null;
  points: number;
  rarityTier: RarityTier | null;
  /** Every valid answer, sorted alphabetically by the server. */
  answers: ValidAnswer[];
}

interface PromptResultWire {
  outcome: PromptResult["outcome"];
  matched_name: string | null;
  points: number;
  rarity_tier: RarityTier | null;
  answers: { name: string; rarity_tier: RarityTier }[];
}

/** The player's result and every valid answer. 409 until the prompt is finished. */
export async function getPromptResult(day: string, position: number): Promise<PromptResult> {
  const wire = await getJson<PromptResultWire>(promptPath(day, position, "result"));
  return {
    outcome: wire.outcome,
    matchedName: wire.matched_name,
    points: wire.points,
    rarityTier: wire.rarity_tier,
    answers: wire.answers.map((answer) => ({
      name: answer.name,
      rarityTier: answer.rarity_tier,
    })),
  };
}
