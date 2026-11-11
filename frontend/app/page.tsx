import { HealthStatus } from "@/components/HealthStatus";

// TODO(F-040): replace this placeholder with the real start screen.
export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-5xl font-bold tracking-tight">UH-NI-ME</h1>
      <p className="text-lg text-zinc-600 dark:text-zinc-400">
        A daily anime trivia game. Coming soon.
      </p>
      <HealthStatus />
    </main>
  );
}
