import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1.5rem" },
    extend: {
      colors: {
        border: "hsl(220 13% 91%)",
        input: "hsl(220 13% 91%)",
        ring: "hsl(215 20% 65%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222 47% 11%)",
        muted: "hsl(210 40% 96%)",
        "muted-foreground": "hsl(215 16% 47%)",
        card: "hsl(0 0% 100%)",
        "card-foreground": "hsl(222 47% 11%)",
        primary: "hsl(221 83% 53%)",
        "primary-foreground": "hsl(210 40% 98%)",
        secondary: "hsl(210 40% 96%)",
        "secondary-foreground": "hsl(222 47% 11%)",
        accent: "hsl(210 40% 96%)",
        "accent-foreground": "hsl(222 47% 11%)",
        destructive: "hsl(0 84% 60%)",
        "destructive-foreground": "hsl(210 40% 98%)",
        success: "hsl(142 71% 45%)",
        "success-foreground": "hsl(210 40% 98%)",
        warning: "hsl(38 92% 50%)",
        "warning-foreground": "hsl(210 40% 98%)",
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.375rem",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
