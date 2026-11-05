/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#12304A",
          900: "#1B405C",
          800: "#315B76",
        },
        surface: "#F7F9FC",
        card: "#FFFFFF",
        accent: {
          teal: "#10A889",
          amber: "#F59E0B",
          coral: "#D65A5A",
        },
        ink: {
          900: "#12304A",
          600: "#64748B",
          400: "#94A3B8",
        },
      },
      fontFamily: {
        // Premium loaded fonts via Google Fonts in index.html
        display: ["Outfit", "system-ui", "-apple-system", "sans-serif"],
        body: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(18,48,74,0.025), 0 4px 12px rgba(18,48,74,0.04)",
      },
    },
  },
  plugins: [],
};
