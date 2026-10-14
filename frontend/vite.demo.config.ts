import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build of the offline demo (frontend/demo.html). Everything goes into ONE JavaScript file
// (no code splitting), so scripts/build_demo.py can inline it into a single HTML that opens
// from file:// — browsers refuse to load separate module files from a local file.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist-demo",
    emptyOutDir: true,
    chunkSizeWarningLimit: 3000,
    assetsInlineLimit: 100_000_000,
    rolldownOptions: { input: "demo.html", output: { codeSplitting: false } },
  },
});
