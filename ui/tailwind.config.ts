import type { Config } from "tailwindcss";

/**
 * Katbook VIP console — "mission control" design tokens.
 * Dark-first, near-black ink, one warm amber signal accent, muted cyan for
 * semantic-search surfaces, semantic green/red reserved for success/error.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "#0B0E14", // app background (near-black)
        panel: "#10151E", // elevated panel, one step lighter
        panel2: "#161D2A", // hovered / nested panel
        line: "#232C3B", // hairline borders
        fg: "#E6EAF2", // primary text
        muted: "#8B94A7", // secondary text
        faint: "#5A6478", // tertiary / disabled
        accent: {
          DEFAULT: "#F59E0B", // warm signal accent (amber) — primary actions + live
          soft: "#FBBF24",
          dim: "#7C4A0C",
        },
        ok: "#34D399", // success only
        bad: "#F87171", // error only
        cyan: "#4CC9D6", // semantic-search surfaces
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: { "2xl": "1rem", "3xl": "1.5rem" },
      boxShadow: {
        glow: "inset 0 1px 0 0 rgba(255,255,255,0.04), 0 0 0 1px rgba(245,158,11,0.10)",
        panel: "inset 0 1px 0 0 rgba(255,255,255,0.03)",
      },
      keyframes: {
        "pulse-accent": {
          "0%,100%": { opacity: "1", boxShadow: "0 0 0 0 rgba(245,158,11,0.45)" },
          "50%": { opacity: "0.75", boxShadow: "0 0 0 6px rgba(245,158,11,0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "pulse-accent": "pulse-accent 1.8s ease-in-out infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
