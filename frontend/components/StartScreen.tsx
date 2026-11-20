"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getTodayPuzzle, type TodayPuzzle } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; puzzle: TodayPuzzle }
  | { kind: "no-puzzle" }
  | { kind: "error" };

const buttonClass =
  "rounded-full bg-foreground px-8 py-3 text-lg font-semibold text-background transition-opacity hover:opacity-80";

const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "full", timeZone: "UTC" });

// `day` is a UTC calendar date (YYYY-MM-DD), so it is formatted in UTC and
// reads the same in every time zone.
function formatDay(day: string): string {
  return dateFormat.format(new Date(`${day}T00:00:00Z`));
}

export function StartScreen() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getTodayPuzzle()
      .then((puzzle) => {
        if (!cancelled) setState(puzzle ? { kind: "ready", puzzle } : { kind: "no-puzzle" });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function retry() {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-zinc-500 dark:text-zinc-400">
        Loading today&apos;s puzzle…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <div role="alert" className="flex flex-col items-center gap-4">
        <p>Couldn&apos;t load today&apos;s puzzle.</p>
        <button type="button" onClick={retry} className={buttonClass}>
          Try again
        </button>
      </div>
    );
  }

  if (state.kind === "no-puzzle") {
    return (
      <div className="flex flex-col items-center gap-2">
        <p className="text-xl font-semibold">No puzzle yet</p>
        <p className="text-zinc-600 dark:text-zinc-400">
          Today&apos;s puzzle isn&apos;t ready. Check back a little later.
        </p>
      </div>
    );
  }

  const { day, promptCount, progress } = state.puzzle;
  // `progress` holds the finished prompts in order, so the next one follows it.
  const nextPosition = progress.length + 1;
  const started = progress.length > 0;
  const complete = progress.length >= promptCount;

  return (
    <div className="flex flex-col items-center gap-4">
      <time dateTime={day} className="text-lg font-medium">
        {formatDay(day)}
      </time>
      {complete ? (
        <>
          <p className="text-zinc-600 dark:text-zinc-400">
            You&apos;ve played today&apos;s puzzle. Come back tomorrow for a new one.
          </p>
          <Link href={`/play/${day}/results`} className={buttonClass}>
            See your results
          </Link>
        </>
      ) : (
        <>
          {started && (
            <p className="text-zinc-600 dark:text-zinc-400">
              Prompt {nextPosition} of {promptCount}
            </p>
          )}
          <Link href={`/play/${day}/${nextPosition}`} className={buttonClass}>
            {started ? "Continue" : "Start"}
          </Link>
        </>
      )}
    </div>
  );
}
