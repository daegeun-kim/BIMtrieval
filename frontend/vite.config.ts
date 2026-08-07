import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The That Open engine ships pre-bundled workers/WASM; excluding these from
// Vite's dep pre-bundling avoids double-optimizing the fragments worker.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  optimizeDeps: {
    exclude: ["@thatopen/components", "@thatopen/fragments", "web-ifc"],
  },
  build: {
    rollupOptions: {
      output: {
        // Split the BIM engine out of the application chunk. Three.js and the
        // That Open packages are the overwhelming majority of the bundle and
        // change only when a dependency is upgraded, so a UI edit no longer
        // invalidates megabytes of cached vendor code on every deploy.
        //
        // This is a CACHING improvement, not a size reduction: the viewer is on
        // the first screen, so every chunk is still fetched on a cold load.
        // Genuinely deferring the engine would mean lazy-loading the viewer,
        // which changes startup behaviour and is not attempted here.
        manualChunks: {
          three: ["three"],
          bim: ["@thatopen/components", "@thatopen/fragments"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false,
  },
});
