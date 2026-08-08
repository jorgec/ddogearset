/** @type {import('tailwindcss').Config} */
export default {
  // Dark is the ONLY theme (docs/DASHBOARD_REDESIGN_SPEC.md). Deliberately not
  // `darkMode: ["class"]` with a light/dark pair: the semantic tokens below are
  // already the dark values, so nothing needs a `dark:` variant to look right.
  // Keeping a second light theme alive would mean maintaining two palettes for
  // a design that only ever ships one.
  content: ["./src/**/*.{html,js,svelte,ts}"],
  theme: {
    extend: {
      colors: {
        // --- SPEC PALETTE (docs/DDO_Gear_Optimizer_Design_Spec.pdf §2) ---
        // Named so components can reach for a material directly
        // (border-carved, text-gold) when a semantic token doesn't fit.
        // None of these names collide with a built-in Tailwind scale — note
        // "carved" rather than "stone", which would shadow Tailwind's own
        // stone-50..950 ramp.
        void: "#121212",        // Void Black — app background
        obsidian: "#1E1E24",    // Obsidian — panel backgrounds
        carved: "#2D2D35",      // Carved Stone — borders & dividers
        vellum: "#E8E3D8",      // Aged Vellum — readout panels / primary text
        "vellum-dark": "#2B271D", // Burnt Vellum — dark readout (the scroll)
        gold: "#D4AF37",        // Artificer Gold — primary headers
        blood: "#8E2B2B",       // Dragon's Blood — warnings / destructive
        arcane: "#3B82F6",      // Arcane Blue — primary actions
        vitality: "#10B981",    // Nature's Vitality — success / status
        steel: "#A8B0BA",       // Polished Steel — secondary text

        // --- SEMANTIC MAPPING ---
        // The tokens every existing component already consumes (bg-card,
        // text-foreground, border-border, …). Re-pointing these at the dark
        // palette is what flips the whole app over in one move — only the
        // handful of components that hardcoded slate/white needed touching.
        background: "#121212",  // void
        foreground: "#E8E3D8",  // vellum — primary text on dark
        border: "#2D2D35",      // carved
        input: "#2D2D35",       // carved
        ring: "#D4AF37",        // gold — focus rings read clearly on void black
        primary: {
          DEFAULT: "#3B82F6",   // arcane — primary actions
          foreground: "#F8FAFC",
        },
        secondary: {
          DEFAULT: "#2D2D35",   // carved — secondary/neutral buttons
          foreground: "#E8E3D8",
        },
        destructive: {
          DEFAULT: "#8E2B2B",   // blood
          foreground: "#E8E3D8",
        },
        muted: {
          DEFAULT: "#2D2D35",   // carved
          foreground: "#A8B0BA", // steel — secondary text
        },
        accent: {
          DEFAULT: "#D4AF37",   // gold
          foreground: "#121212", // void — dark text on gold for contrast
        },
        popover: {
          DEFAULT: "#1E1E24",   // obsidian
          foreground: "#E8E3D8",
        },
        card: {
          DEFAULT: "#1E1E24",   // obsidian
          foreground: "#E8E3D8",
        },
      },
      fontFamily: {
        // §3 — ornate serif for headings, clean sans for data, mono for the
        // arcane console. All three are bundled via @fontsource rather than
        // linked from a CDN: this ships as an offline desktop app.
        display: ['Cinzel', 'Merriweather', 'Georgia', 'serif'],
        sans: ['Inter', 'Roboto', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['"Fira Code"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        // §4.2 — sockets read as physical recesses waiting to be filled.
        socket: "inset 0 2px 6px rgba(0,0,0,0.75), inset 0 0 0 1px rgba(0,0,0,0.4)",
        // §6 — hover "presses" an element inward.
        press: "inset 0 1px 3px rgba(0,0,0,0.6)",
        // §4.4 — the console's arcane glow.
        arcane: "0 0 12px rgba(59,130,246,0.25), inset 0 0 24px rgba(59,130,246,0.06)",
        gold: "0 0 10px rgba(212,175,55,0.25)",
      },
    },
  },
  plugins: [],
}
