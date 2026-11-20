"use client";

import { useId, useState } from "react";

import { RARITY_TIERS, type RarityTier, type ValidAnswer } from "@/lib/api";

// Case-, accent- and macron-insensitive, so "kyoso" finds "Kyōsōgiga". This
// is only a display filter; answer matching is done by the server (F-003).
function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

/**
 * Every valid answer of a finished prompt (F-035), with a search box and a
 * rarity filter. Both run client-side. The list keeps the server's order,
 * which is alphabetical.
 */
export function AnswerBrowser({ answers }: { answers: ValidAnswer[] }) {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<RarityTier | "all">("all");
  const searchId = useId();
  const tierId = useId();
  const listId = useId();

  const needle = fold(query.trim());
  const shown = answers.filter(
    (answer) =>
      (tier === "all" || answer.rarityTier === tier) &&
      (needle === "" || fold(answer.name).includes(needle)),
  );

  return (
    <section className="flex w-full flex-col gap-3 text-left">
      <div className="flex gap-2">
        <label htmlFor={searchId} className="sr-only">
          Search answers
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search answers"
          autoComplete="off"
          aria-controls={listId}
          className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-background px-3 py-2 dark:border-zinc-700"
        />
        <label htmlFor={tierId} className="sr-only">
          Rarity
        </label>
        <select
          id={tierId}
          value={tier}
          onChange={(event) => setTier(event.target.value as RarityTier | "all")}
          aria-controls={listId}
          className="rounded-lg border border-zinc-300 bg-background px-2 py-2 dark:border-zinc-700"
        >
          <option value="all">All tiers</option>
          {RARITY_TIERS.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <p aria-live="polite" className="text-sm text-zinc-500 dark:text-zinc-400">
        {shown.length} of {answers.length} answers
      </p>

      <ul
        id={listId}
        aria-label="Valid answers"
        className="max-h-80 divide-y divide-zinc-200 overflow-y-auto rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800"
      >
        {shown.map((answer) => (
          <li key={answer.name} className="flex items-center justify-between gap-3 px-3 py-2">
            <span data-answer-name>{answer.name}</span>
            <span className="shrink-0 text-sm text-zinc-500 dark:text-zinc-400">
              {answer.rarityTier}
            </span>
          </li>
        ))}
      </ul>
      {shown.length === 0 && (
        <p className="text-center text-zinc-500 dark:text-zinc-400">No answers match.</p>
      )}
    </section>
  );
}
