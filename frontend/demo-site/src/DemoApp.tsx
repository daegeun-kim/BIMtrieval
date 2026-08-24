// Demo shell (spec_v013 §4.6).
//
// Renders the real `App` unmodified and adds three things around it: the
// disclosure banner, the effect that skips the model-confirmation click, and the
// curtain that hides the viewer until the opening frame is posed.
//
// The confirmation is PERFORMED, not bypassed — this calls the same public
// `confirmAndLoadModel` the confirm dialog calls, so the load path a visitor
// sees is the genuine one. Only the click is automated, because a portfolio
// visitor should meet the building, not a model picker with one row in it.
import { useEffect, useRef, useState } from "react";

import App from "../../src/App";
import { controller } from "../../src/state/controller";
import { useStore } from "../../src/state/store";
import DemoBanner from "./DemoBanner";
import { frameForDemo } from "./demoCamera";

export default function DemoApp() {
  const models = useStore((s) => s.models);
  const activeModel = useStore((s) => s.activeModel);
  const loadPhase = useStore((s) => s.loadPhase);
  // Watched only so the obstruction effect below re-runs whenever the
  // application's own does — it keys off exactly these.
  const panelWidth = useStore((s) => s.panelWidth);
  const panelCollapsed = useStore((s) => s.panelCollapsed);
  const componentOpen = useStore((s) => s.componentGuid !== null);
  const explanationOpen = useStore((s) => s.explanation !== null);
  const started = useRef(false);
  const framed = useRef(false);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    if (started.current || activeModel !== null) return;
    const first = models[0];
    if (!first) return;
    started.current = true;

    // The application defaults to "standard" quality, which is right when the
    // user chose to run it on their own machine. A public demo has no idea what
    // it has landed on — a phone, an old laptop, a recruiter's locked-down
    // work machine — so it opens on "fast" and lets the visitor turn it up.
    //
    // Set BEFORE the load, not after: the mode is recorded on the adapter and
    // applied as the model comes in, so the geometry arrives at the intended
    // quality instead of being rebuilt a moment later.
    //
    // This changes only the demo's starting point. The Fine / Standard / Fast
    // control is the real one from `src/components/VisualizationModeControl`,
    // still in the bottom-left readout, still fully operable.
    void controller.setVisualizationMode("fast");

    void controller.confirmAndLoadModel(first);
  }, [models, activeModel]);

  // Pose the opening frame once the model is in the scene, then lift the
  // curtain. The application's own fit has already run by this point and framed
  // the model side-on; posing and revealing in the same step is what keeps that
  // intermediate view from ever reaching the screen.
  useEffect(() => {
    if (loadPhase === "error") {
      // A failed load must never leave the curtain down — the error belongs on
      // screen, not behind a blank panel.
      setRevealed(true);
      return;
    }
    if (framed.current || loadPhase !== "ready") return;
    framed.current = true;
    void frameForDemo().finally(() => setRevealed(true));
  }, [loadPhase]);

  // On a phone the panels sit BELOW the viewer rather than beside it, so
  // nothing obstructs it horizontally. The application computes an obstruction
  // from the chat panel's width and feeds it to the camera, which is right for
  // the desktop layout and badly wrong for this one — the camera would frame
  // the model into a sliver on the left of a viewport that is actually full
  // width.
  //
  // Child effects run before parent effects in React, and `App` is a child
  // here, so this lands after the application's own call and wins. The store
  // values it depends on are exactly the ones the application keys off, so the
  // two stay in step rather than this going stale after a panel resize.
  useEffect(() => {
    const apply = () => {
      if (window.matchMedia("(max-width: 768px)").matches) {
        controller.viewer.setViewportObstruction(0);
      }
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, [panelWidth, panelCollapsed, componentOpen, explanationOpen, loadPhase]);

  return (
    <>
      <App />
      {/* Covers the canvas only — the application's own loading card sits above
          it (z-index 8) and stays visible, so the wait still reads as progress
          rather than a blank screen.

          The spinner fills the gap before that card exists: the model list has
          to arrive and the load has to start before the app renders any phase
          indicator, and a motionless grey field in the meantime reads as a page
          that has failed rather than one that is working. `aria-hidden` follows
          the reveal so the status is announced while it matters and goes quiet
          once the curtain is transparent but still in the DOM. */}
      <div className={`demo-curtain${revealed ? " is-lifted" : ""}`} aria-hidden={revealed}>
        <div className="demo-curtain-inner" role="status">
          <div className="demo-spinner" />
          <p className="demo-curtain-text">Loading the building model</p>
        </div>
      </div>
      <DemoBanner />
    </>
  );
}
