import type { Config } from "tailwindcss";

/**
 * Katbook VIP console — "Sky" design tokens.
 * Bright, clean light-mode SaaS (Notion/Linear light-mode inspired). White
 * surfaces, soft shadows, sky-blue accent. No glass/blur, no glow — flat,
 * airy, professional.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "#FFFFFF", // solid-white base (sticky header, opaque chrome)
        panel: "#FFFFFF", // card fill — solid white
        panel2: "#F1F5F9", // nested surface (slate-100) — inputs, chips, stat tiles
        line: "#E2E8F0", // hairline borders (slate-200)
        fg: "#0F172A", // heading text — dark slate, not pure black
        muted: "#64748B", // secondary text (slate-500)
        faint: "#94A3B8", // tertiary text / table header labels (slate-400)
        accent: {
          // sky-700, not the lighter sky-500 (#0EA5E9): white text on #0EA5E9 is
          // ~2.4:1 contrast (fails WCAG AA's 4.5:1) — every solid-fill button/pill
          // with white text was under-contrast. sky-700 reads unmistakably as
          // "sky blue" while giving ~6:1 for both white-on-fill and text-on-white.
          DEFAULT: "#0369A1",
          soft: "#7DD3FC", // lighter sky — hover TINTS/backgrounds only, never as text
          dim: "#075985", // sky-800 — hover/pressed state on solid buttons
        },
        ok: "#22C55E", // success ("done") — soft green
        bad: "#DC2626", // error ("failed") — red-600, legible as plain text on white
        cyan: "#06B6D4", // secondary hue for search/semantic surfaces
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: { "2xl": "1rem", "3xl": "1.5rem" },
      boxShadow: {
        // spec formula: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04)
        panel: "0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)",
        // slightly stronger for hover / emphasis — still soft, no color glow
        glow: "0 4px 16px rgba(15,23,42,0.08), 0 2px 6px rgba(15,23,42,0.05)",
      },
      keyframes: {
        "pulse-accent": {
          "0%,100%": { opacity: "1", boxShadow: "0 0 0 0 rgba(3,105,161,0.4)" },
          "50%": { opacity: "0.7", boxShadow: "0 0 0 6px rgba(3,105,161,0)" },
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
