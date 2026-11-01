import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17171f",
        mute: "#5e5e6c",
        line: "#ececf2",
        pink: "#ff2f86",
        blush: "#fff1f6",
        wash: "#f7f7f8",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
      },
      boxShadow: {
        card: "0 16px 50px rgba(23, 23, 31, 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
