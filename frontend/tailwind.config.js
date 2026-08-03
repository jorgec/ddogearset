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
        background: "#0d131c",
        foreground: "#f4f5f7",
        primary: {
          DEFAULT: "#00798c",
          foreground: "#f4f5f7",
        },
        secondary: {
          DEFAULT: "#53a3ae",
          foreground: "#0d131c",
        },
        destructive: {
          DEFAULT: "#d1495b",
          foreground: "#f4f5f7",
        },
        muted: {
          DEFAULT: "#1c2430",
          foreground: "#7c858f",
        },
        accent: {
          DEFAULT: "#edae49",
          foreground: "#0d131c",
        },
        popover: {
          DEFAULT: "#1c2430",
          foreground: "#f4f5f7",
        },
        card: {
          DEFAULT: "#1c2430",
          foreground: "#f4f5f7",
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
