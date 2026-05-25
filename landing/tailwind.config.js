/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      colors: {
        brand: {
          bg: '#0F172A',
          card: '#1E293B',
          blue: '#2563EB',
          cyan: '#06B6D4',
        },
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #2563EB, #06B6D4)',
      },
    },
  },
  plugins: [],
}
