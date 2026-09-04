/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dark workspace surface — matches the Admin Overview page's
        // palette exactly (#0B0C1E/#12132B/#8B5CF6), since the whole
        // app now uses the same look Admin already had.
        base: {
          void: "#0B0C1E", // page background
          panel: "#12132B", // cards
          "panel-2": "#171933", // nested/inset panels
          border: "#232544",
        },
        ink: {
          DEFAULT: "#F4F4F8", // headings / primary text
          muted: "#9195AE", // secondary text
          faint: "#6B6E89", // tertiary / placeholder text
        },
        accent: {
          violet: "#8B5CF6",
          blue: "#3B82F6",
          cyan: "#22D3EE",
          green: "#22C55E",
          amber: "#F59E0B",
          orange: "#FB923C",
          pink: "#EC4899",
        },
        // Sidebar keeps its own token group (was always dark, even
        // during the earlier light-theme pass) — same values as
        // `base`/`ink` now in practice, kept distinct so the sidebar
        // never gets swept into a future retheme unintentionally.
        nav: {
          bg: "#0B0C1E",
          panel: "#14162E",
          border: "#232544",
          text: "#C6C8DA",
          muted: "#7A7E9C",
        },
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'Inter'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px -8px var(--tw-shadow-color)",
        card: "0 1px 2px rgba(0, 0, 0, 0.24), 0 1px 3px rgba(0, 0, 0, 0.32)",
      },
      animation: {
        "pulse-slow": "pulse 3.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "orbit-spin": "orbit-spin 60s linear infinite",
        "flow-dash": "flow-dash 3s linear infinite",
      },
      keyframes: {
        "orbit-spin": {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
        "flow-dash": {
          to: { strokeDashoffset: "-24" },
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
