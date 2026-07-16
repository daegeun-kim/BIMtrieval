import { useEffect, useRef } from "react";

import { controller } from "../state/controller";
import { PreviewScene } from "../viewer/PreviewScene";
import { PREVIEW } from "../viewer/viewerTheme";

// Preview viewport height (task15 §4: doubled to ~320px). min(_, 36vh) keeps it
// responsive on short application viewports; the value itself is centralized
// in viewerTheme so it lives next to the other preview constants.
const PREVIEW_HEIGHT = `min(${PREVIEW.viewportHeightPx}px, 36vh)`;

// Lazy isolated 3D preview of one instance (task14 §5). Initializes only when
// mounted (i.e. when the panel is open) and disposes every GPU/listener resource
// on unmount or subject change, so no duplicate render loop can survive.
export default function ComponentPreview({ guid }: { guid: string }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<PreviewScene | null>(null);
  const statusRef = useRef<HTMLParagraphElement | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    const scene = new PreviewScene(host);
    sceneRef.current = scene;

    void (async () => {
      const extracted = await controller.viewer.extractItemGeometry(guid);
      // Guard: the subject may have changed while we awaited the geometry.
      if (cancelled) return;
      const ok = extracted ? scene.mount(extracted.meshes, extracted.role) : false;
      if (!ok && statusRef.current) {
        statusRef.current.textContent = "No 3D geometry for this object.";
      }
    })();

    const onResize = () => scene.resize();
    window.addEventListener("resize", onResize);

    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      scene.dispose();
      sceneRef.current = null;
    };
  }, [guid]);

  return (
    <div className="cp-preview">
      <div
        className="cp-preview-canvas"
        style={{ height: PREVIEW_HEIGHT }}
        ref={hostRef}
        data-testid="component-preview"
      />
      <p className="cp-preview-status" ref={statusRef} aria-live="polite" />
    </div>
  );
}
