/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        oci: {
          red: '#C74634',
          blue: '#312D2A',
          light: '#F8F8F8',
        }
      }
    },
  },
  plugins: [],
}
