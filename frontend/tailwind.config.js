/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./src/**/*.{html,js,svelte,ts}"],
  theme: {
    extend: {
      colors: {
        border: "#d9dde1",
        input: "#d9dde1",
        ring: "#00798c",
        background: "#f4f5f7",
        foreground: "#0d131c",
        primary: {
          DEFAULT: "#00798c",
          foreground: "#f4f5f7",
        },
        secondary: {
          DEFAULT: "#53a3ae",
          foreground: "#0d131c",
        },
        destructive: {
          DEFAULT: "#610414",
          foreground: "#e1d5d7",
        },
        muted: {
          DEFAULT: "#d9dde1",
          foreground: "#1c2430",
        },
        accent: {
          DEFAULT: "#edae49",
          foreground: "#0d131c",
        },
        popover: {
          DEFAULT: "#ffffff",
          foreground: "#0d131c",
        },
        card: {
          DEFAULT: "#ffffff",
          foreground: "#0d131c",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
}
