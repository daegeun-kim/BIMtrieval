import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The public static demo (spec_v013). This config is the ENTIRE difference
// between the demo and the real application: it swaps two modules by alias and
// changes the base path. Nothing under `frontend/src/` is modified.
//
// Engine settings that must not drift from the real build (the pre-bundling
// exclusions and the vendor chunk split) are restated here with a pointer rather
// than imported, because `../vite.config.ts` also carries the Vitest block and
// the dev-server port, which the demo must not inherit. Keep the two lists in
// step: frontend/vite.config.ts is the source of truth.

const here = fileURLToPath(new URL(".", import.meta.url));
const demoSrc = (file: string) => fileURLToPath(new URL(`./src/${file}`, import.meta.url));

export default defineConfig({
  root: here,

  // GitHub Pages serves this project site from `/BIMtrieval/` (spec_v013 §2).
  // Overridable so a later move to a custom subdomain is a one-value change to
  // `/` rather than an edit here (spec_v013 §2.2).
  base: process.env.VITE_DEMO_BASE ?? "/BIMtrieval/",

  plugins: [react()],

  // Not 5173: the real `npm run dev` uses that port with strictPort, so both can
  // run side by side while the demo is built.
  server: { port: 5174, strictPort: true },

  resolve: {
    // The two substitutions (spec_v013 §4). `api` is exported once and imported
    // once (src/state/controller.ts), and `Composer` is a zero-prop default
    // export imported once (src/chat/ChatPanel.tsx), so replacing these two
    // modules replaces the entire backend and the entire input surface while
    // every other component runs unmodified and unaware.
    //
    // `frontend/tests/demo-site.test.ts` asserts both remain single-import, so a
    // refactor that adds a second import site fails the offline gate instead of
    // silently leaving half the demo live.
    // Both patterns must match the WHOLE specifier: a regex alias substitutes
    // only the matched span, so anchoring on `/api/client` alone would leave the
    // leading `../` glued to the absolute replacement path.
    alias: [
      { find: /^.*\/api\/client$/, replacement: demoSrc("fixtureClient.ts") },
      { find: /^\.\/Composer$/, replacement: demoSrc("DemoComposer.tsx") },
    ],
  },

  optimizeDeps: {
    exclude: ["@thatopen/components", "@thatopen/fragments", "web-ifc"],
  },

  build: {
    outDir: fileURLToPath(new URL("../dist-demo", import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three"],
          bim: ["@thatopen/components", "@thatopen/fragments"],
        },
      },
    },
  },
});
