"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  getPromptResult,
  getTodayPuzzle,
  startPrompt,
  submitGuess,
  type PromptResult,
  type StartedPrompt,
} from "@/lib/api";

import { AnswerBrowser } from "./AnswerBrowser";

/** How often the countdown re-renders. */
const TICK_MS = 250;
/** How long "not a valid answer" stays up. */
const FEEDBACK_MS = 2000;
/**
 * The result endpoint answers 409 until the time limit plus the server's grace
 * has passed, and `deadline` excludes the grace, so the client retries.
 */
const RESULT_RETRY_MS = 1000;

const buttonClass =
  "rounded-full bg-foreground px-8 py-3 text-lg font-semibold text-background transition-opacity hover:opacity-80";

const mutedClass = "text-zinc-600 dark:text-zinc-400";

// A monotonic clock: the countdown never reads the player's wall clock, which
// may be wrong or change while the prompt is open.
function monotonicNow(): number {
  return performance.now();
}

function isStatus(error: unknown, ...statuses: number[]): boolean {
  return error instanceof ApiError && statuses.includes(error.status);
}

export function PromptScreen({ day, position }: { day: string; position: number }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const submitting = useRef(false);

  const [prompt, setPrompt] = useState<StartedPrompt | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [promptCount, setPromptCount] = useState<number | null>(null);

  // Monotonic time at which the countdown reaches zero.
  const [endsAt, setEndsAt] = useState<number | null>(null);
  const [timeLeftMs, setTimeLeftMs] = useState(0);
  // The prompt is finished: accepted, or out of time. The result comes next.
  const [ended, setEnded] = useState(false);
  const [timeUp, setTimeUp] = useState(false);

  const [text, setText] = useState("");
  const [feedback, setFeedback] = useState("");
  const [outOfGuesses, setOutOfGuesses] = useState(false);

  const [result, setResult] = useState<PromptResult | null>(null);
  const [resultError, setResultError] = useState(false);
  const [resultAttempt, setResultAttempt] = useState(0);

  // Start (or resume) the prompt. The time left is the server's deadline − now,
  // counted from when the response arrived, so latency doesn't eat into it.
  useEffect(() => {
    let cancelled = false;
    startPrompt(day, position)
      .then((started) => {
        if (cancelled) return;
        const leftMs = Date.parse(started.deadline) - Date.parse(started.now);
        setPrompt(started);
        setEndsAt(monotonicNow() + leftMs);
        setTimeLeftMs(Math.max(0, leftMs));
        if (leftMs <= 0) {
          setTimeUp(true);
          setEnded(true);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // 404: the day is over (or never existed). 409: an earlier prompt is
        // unfinished. Home knows where the player should be.
        if (isStatus(error, 404, 409)) router.replace("/");
        else setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [day, position, loadAttempt, router]);

  // Only needed to tell the last prompt apart, for the Next link.
  useEffect(() => {
    let cancelled = false;
    getTodayPuzzle()
      .then((puzzle) => {
        if (!cancelled && puzzle?.day === day) setPromptCount(puzzle.promptCount);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [day]);

  useEffect(() => {
    if (endsAt === null || ended) return;
    const interval = setInterval(() => {
      const leftMs = endsAt - monotonicNow();
      setTimeLeftMs(Math.max(0, leftMs));
      if (leftMs <= 0) {
        setTimeUp(true);
        setEnded(true);
      }
    }, TICK_MS);
    return () => clearInterval(interval);
  }, [endsAt, ended]);

  // Once finished, load the result and the answer list. Fetching the result of
  // a timed-out prompt is also what records it as expired on the server.
  useEffect(() => {
    if (!ended || result) return;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    function load() {
      getPromptResult(day, position)
        .then((loaded) => {
          if (!cancelled) setResult(loaded);
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          if (isStatus(error, 409)) retry = setTimeout(load, RESULT_RETRY_MS);
          else if (isStatus(error, 404)) router.replace("/");
          else setResultError(true);
        });
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(retry);
    };
  }, [ended, result, day, position, resultAttempt, router]);

  useEffect(() => () => clearTimeout(feedbackTimer.current), []);

  function showFeedback(message: string, brief: boolean) {
    clearTimeout(feedbackTimer.current);
    setFeedback(message);
    if (brief) feedbackTimer.current = setTimeout(() => setFeedback(""), FEEDBACK_MS);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const guess = text.trim();
    if (guess === "" || submitting.current || outOfGuesses || ended) return;

    submitting.current = true;
    try {
      const outcome = await submitGuess(day, position, guess);
      if (outcome.finished) {
        if (!outcome.accepted) setTimeUp(true);
        setEnded(true);
        return;
      }
      setText("");
      showFeedback("Not a valid answer", true);
      inputRef.current?.focus();
    } catch (error) {
      if (isStatus(error, 429)) {
        setOutOfGuesses(true);
        showFeedback("Out of guesses. Wait for the timer to run out.", false);
      } else if (isStatus(error, 409)) {
        // Already answered, e.g. in another tab.
        setEnded(true);
      } else if (isStatus(error, 404, 401)) {
        // 404: the day rolled over. 401: the player cookie is gone.
        router.replace("/");
      } else {
        showFeedback("Couldn't send your guess. Try again.", true);
        inputRef.current?.focus();
      }
    } finally {
      submitting.current = false;
    }
  }

  if (loadError) {
    return (
      <div role="alert" className="flex flex-col items-center gap-4 text-center">
        <p>Couldn&apos;t load this prompt.</p>
        <button
          type="button"
          onClick={() => {
            setLoadError(false);
            setLoadAttempt((n) => n + 1);
          }}
          className={buttonClass}
        >
          Try again
        </button>
      </div>
    );
  }

  if (!prompt) {
    return (
      <p role="status" className={`text-center ${mutedClass}`}>
        Loading the prompt…
      </p>
    );
  }

  const isLast = promptCount !== null && position >= promptCount;
  const nextHref =
    promptCount === null ? "/" : isLast ? `/play/${day}/results` : `/play/${day}/${position + 1}`;
  const seconds = Math.ceil(timeLeftMs / 1000);
  const limitMs = Date.parse(prompt.deadline) - Date.parse(prompt.startedAt);

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-2 text-center">
        <p className={`text-sm font-medium uppercase tracking-wide ${mutedClass}`}>
          {promptCount === null ? `Prompt ${position}` : `Prompt ${position} of ${promptCount}`}
        </p>
        <h1 className="text-2xl font-bold sm:text-3xl">{prompt.text}</h1>
      </header>

      {!ended && (
        <>
          <div className="flex items-center gap-3">
            <div
              className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
              aria-hidden
            >
              <div
                className="h-full bg-foreground transition-[width] duration-200 ease-linear"
                style={{ width: `${limitMs > 0 ? (100 * timeLeftMs) / limitMs : 0}%` }}
              />
            </div>
            <div
              role="timer"
              aria-label="Time left"
              className="w-10 text-right text-xl font-semibold tabular-nums"
            >
              {seconds}
            </div>
          </div>

          <form onSubmit={onSubmit} className="flex gap-2">
            <label htmlFor="answer" className="sr-only">
              Your answer
            </label>
            <input
              ref={inputRef}
              id="answer"
              type="text"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                if (!outOfGuesses) setFeedback("");
              }}
              disabled={outOfGuesses}
              autoFocus
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="send"
              maxLength={200}
              placeholder="Type an answer"
              className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-background px-4 py-3 text-lg disabled:opacity-50 dark:border-zinc-700"
            />
            <button
              type="submit"
              disabled={outOfGuesses}
              className="rounded-lg bg-foreground px-5 py-3 font-semibold text-background disabled:opacity-50"
            >
              Guess
            </button>
          </form>
          <p role="status" aria-live="polite" className={`min-h-6 text-center ${mutedClass}`}>
            {feedback}
          </p>
        </>
      )}

      {ended && !result && (
        <div className="flex flex-col items-center gap-3 text-center">
          {timeUp && <p className="text-xl font-semibold">Time&apos;s up</p>}
          {resultError ? (
            <div role="alert" className="flex flex-col items-center gap-3">
              <p>Couldn&apos;t load the result.</p>
              <button
                type="button"
                onClick={() => {
                  setResultError(false);
                  setResultAttempt((n) => n + 1);
                }}
                className={buttonClass}
              >
                Try again
              </button>
            </div>
          ) : (
            <p className={mutedClass}>Loading the answers…</p>
          )}
        </div>
      )}

      {result && (
        <>
          <section className="flex flex-col items-center gap-1 text-center">
            {result.outcome === "accepted" ? (
              <>
                <p className="text-2xl font-bold" data-matched-name>
                  {result.matchedName}
                </p>
                <p className="text-lg">+{result.points} points</p>
                <p className={mutedClass}>
                  Rarity: <span data-player-tier>{result.rarityTier}</span>
                </p>
              </>
            ) : (
              <>
                <p className="text-2xl font-bold">Time&apos;s up</p>
                <p className="text-lg">{result.points} points</p>
              </>
            )}
          </section>

          <div className="flex justify-center">
            <Link href={nextHref} className={buttonClass}>
              {isLast ? "See your results" : "Next"}
            </Link>
          </div>

          <AnswerBrowser answers={result.answers} />
        </>
      )}
    </div>
  );
}
