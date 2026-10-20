import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        gemini: {
          bg: "#131314",
          surface: "#1e1f20",
          surfaceHover: "#282a2c",
          border: "#333537",
          text: "#e3e3e3",
          muted: "#9aa0a6",
          accentBlue: "#4b90ff",
          accentViolet: "#a855f7",
        },
      },
    },
  },
  plugins: [],
};

export default config;
