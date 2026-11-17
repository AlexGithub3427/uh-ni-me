import { StartScreen } from "@/components/StartScreen";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-10 px-6 py-12 text-center">
      <header className="flex flex-col gap-3">
        <h1 className="text-5xl font-bold tracking-tight">UH-NI-ME</h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          The daily anime trivia game where rarer answers score more.
        </p>
      </header>

      <StartScreen />

      <section aria-labelledby="how-to-play" className="flex flex-col gap-3 text-left">
        <h2 id="how-to-play" className="text-center text-xl font-semibold">
          How to play
        </h2>
        <ul className="list-disc space-y-2 pl-5 text-zinc-600 dark:text-zinc-400">
          <li>Each day has 7 prompts, like &ldquo;Name an anime by MAPPA&rdquo;.</li>
          <li>
            You get 25 seconds per prompt, and the timer starts as soon as the prompt appears.
          </li>
          <li>Any valid answer counts. Wrong guesses can be retried until time runs out.</li>
          <li>The rarer your answer, the more points it scores, up to 100 per prompt.</li>
          <li>One game a day. A new puzzle arrives at 00:00 UTC.</li>
        </ul>
      </section>
    </main>
  );
}
