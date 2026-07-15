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
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false,
  },
});
