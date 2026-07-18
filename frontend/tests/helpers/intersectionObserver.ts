// Per-test controllable IntersectionObserver mock (tasks/task18.md §10). The
// global default in tests/setup.ts always reports "visible" immediately;
// tests that need to drive visibility explicitly (e.g. PreviewScene pausing
// off-screen) should install this instead via vi.stubGlobal, then call
// `trigger(isIntersecting)` to simulate a visibility change, and `restore()`
// in an afterEach/finally to put the default stub back.
import { vi } from "vitest";

export function mockIntersectionObserver(): {
  trigger: (isIntersecting: boolean) => void;
  restore: () => void;
} {
  let callback: IntersectionObserverCallback | null = null;
  let observedTarget: Element | null = null;

  class ControllableIntersectionObserver {
    constructor(cb: IntersectionObserverCallback) {
      callback = cb;
    }
    observe(target: Element) {
      observedTarget = target;
    }
    unobserve() {
      observedTarget = null;
    }
    disconnect() {
      observedTarget = null;
    }
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }

  vi.stubGlobal("IntersectionObserver", ControllableIntersectionObserver as never);

  return {
    trigger(isIntersecting: boolean) {
      if (!callback || !observedTarget) return;
      callback(
        [{ isIntersecting, target: observedTarget } as IntersectionObserverEntry],
        undefined as unknown as IntersectionObserver,
      );
    },
    restore() {
      vi.unstubAllGlobals();
    },
  };
}
