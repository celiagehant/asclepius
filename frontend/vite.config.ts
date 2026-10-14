import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development (`npm run dev`, port 5173) API calls are proxied to FastAPI on 8000.
// In normal use FastAPI serves the built files from frontend/dist on the same origin.
export default defineConfig({
  plugins: [react()],
  // three.js lives in its own lazily loaded chunk (the 3D body), so a large chunk there is expected.
  build: { chunkSizeWarningLimit: 1100 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
