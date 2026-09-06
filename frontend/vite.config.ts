import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Docker Desktop on Windows doesn't reliably forward native filesystem
    // change events across the bind-mounted volume, so Vite's default
    // watcher can silently miss edits (observed during Week 6 verification:
    // an edited CSS file kept serving its old content through HMR/module
    // cache indefinitely). Polling is slightly heavier but actually detects
    // changes in this setup.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
  build: {
    rollupOptions: {
      output: {
        // maplibre-gl is the overwhelming majority of the production
        // bundle (~41MB unpacked vs. ~4.4MB for react-dom) and changes far
        // less often than this project's own code. Splitting it into its
        // own chunk doesn't reduce total bytes shipped, but lets browsers
        // cache it independently of app-code changes -- a plain,
        // one-library manualChunks entry, not a general chunking strategy.
        manualChunks: {
          maplibre: ["maplibre-gl"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
