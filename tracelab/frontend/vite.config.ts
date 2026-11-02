import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `make dev-api` serves the backend on :8000
    proxy: { "/api": "http://localhost:8000" },
  },
});
