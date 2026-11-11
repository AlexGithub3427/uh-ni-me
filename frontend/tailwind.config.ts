import type { Config } from "tailwindcss";

// Design tokens live here (loaded from app/globals.css via @config).
// TODO(F-043): add color, font and spacing tokens, one color per rarity tier.
const config: Config = {
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
    },
  },
};

export default config;
