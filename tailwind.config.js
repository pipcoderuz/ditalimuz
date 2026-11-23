const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const primary = Object.fromEntries(shades.map((s) => [s, `rgb(var(--p-${s}) / <alpha-value>)`]));

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./assets/src/**/*.js",
    "./*/templatetags/*.py",
    "./node_modules/flowbite/**/*.js",
  ],
  theme: {
    extend: {
      colors: { primary }, // asosiy rang admin tomonidan (Sayt dizayni) o'zgartiriladi — CSS o'zgaruvchilari orqali
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
    },
  },
  plugins: [require("flowbite/plugin"), require("@tailwindcss/typography")],
};
