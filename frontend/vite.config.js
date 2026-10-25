import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the screens run on Vite and call the Flask API on port 5000.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:5000" } },
});
