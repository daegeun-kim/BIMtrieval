import { useEffect, useRef } from "react";

import { controller } from "../state/controller";

// Mounts the imperative viewer once and forwards container resizes to it. This
// component intentionally has no reactive state so it never re-renders on camera
// movement (spec_v006 §14).
export default function ViewerCanvas() {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let disposed = false;

    void controller.initViewer(el).catch(() => {
      // initialization failures surface through the load/error UI, not a crash
    });

    const ro = new ResizeObserver(() => {
      if (!disposed) controller.viewer.resize();
    });
    ro.observe(el);

    return () => {
      disposed = true;
      ro.disconnect();
    };
  }, []);

  return <div ref={ref} className="viewer-canvas" aria-hidden="true" />;
}
