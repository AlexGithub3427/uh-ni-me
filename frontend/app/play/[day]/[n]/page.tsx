import type { Viewport } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PromptRoute } from "@/components/PromptRoute";

// When the on-screen keyboard opens, shrink the page instead of overlaying it.
// The input sits near the top, so it stays visible above the keyboard.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  interactiveWidget: "resizes-content",
};

export default function PromptPage({ params }: PageProps<"/play/[day]/[n]">) {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-6 px-4 pt-6 pb-12 sm:pt-12">
      <Link href="/" className="self-center text-lg font-bold tracking-tight">
        UH-NI-ME
      </Link>
      {/* The params are only known at request time (Cache Components). */}
      <Suspense
        fallback={
          <p role="status" className="text-center text-zinc-600 dark:text-zinc-400">
            Loading the prompt…
          </p>
        }
      >
        <PromptRoute params={params} />
      </Suspense>
    </main>
  );
}
