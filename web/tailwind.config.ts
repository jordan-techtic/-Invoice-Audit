import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    // The rail collapses at 1024px and below (tablet landscape counts as tablet).
    screens: { sm: "640px", md: "768px", lg: "1025px", xl: "1280px", "2xl": "1536px" },
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        sunken: "var(--surface-sunken)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        ink: "var(--ink)",
        muted: "var(--ink-muted)",
        primary: "var(--primary)",
        "primary-hover": "var(--primary-hover)",
        money: "var(--money)",
        amber: "var(--amber)",
        "amber-soft": "var(--amber-soft)",
        confirmed: "var(--confirmed)",
        "confirmed-soft": "var(--confirmed-soft)",
        dismissed: "var(--dismissed)",
        "dismissed-soft": "var(--dismissed-soft)",
        danger: "var(--danger)",
      },
      fontFamily: {
        sans: ["var(--font-figtree)", "system-ui", "sans-serif"],
      },
      fontSize: {
        sm: ["0.875rem", "1.25rem"],
        base: ["1rem", "1.5rem"],
        lg: ["1.25rem", "1.75rem"],
        xl: ["1.5625rem", "2rem"],
        "2xl": ["1.9375rem", "2.375rem"],
        hero: ["4rem", "4.25rem"],
      },
      maxWidth: { page: "1200px", prose: "68ch" },
    },
  },
  plugins: [],
} satisfies Config;
