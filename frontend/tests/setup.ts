import "@testing-library/jest-dom/vitest";

// jsdom lacks these APIs that the viewer/layout code touches; stub them so
// component tests render without a real WebGL context or ResizeObserver.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as never);

// jsdom has no indexedDB; tests mock the `idb` module, but the cache module
// feature-detects `indexedDB` before touching it, so provide a marker object.
(globalThis as Record<string, unknown>).indexedDB =
  (globalThis as Record<string, unknown>).indexedDB ?? {};

if (!globalThis.matchMedia) {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as never;
}
