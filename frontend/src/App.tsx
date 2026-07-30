import { useEffect, useState } from "react";

import ChatPanel from "./chat/ChatPanel";
import ComponentPanel from "./components/ComponentPanel";
import ConfirmDialog from "./components/ConfirmDialog";
import StatusReadout from "./components/StatusReadout";
import ViewerControls from "./components/ViewerControls";
import ViewerOverlay from "./components/ViewerOverlay";
import ExplanationPanel from "./explain/ExplanationPanel";
import { controller } from "./state/controller";
import {
  effectivePanelWidth,
  effectiveViewportObstructionPx,
  explanationColumnWidthPx,
  useStore,
} from "./state/store";
import ViewerCanvas from "./viewer/ViewerCanvas";

// Width of the collapsed chat restore tab, so the component panel still docks
// beside it rather than under it.
const COLLAPSED_CHAT_WIDTH = 40;

/** Live viewport width, so the fixed vw-based Task 26 column can be measured in
 *  px for the single obstruction calculation the viewer reads. */
function useViewportWidth(): number {
  const [width, setWidth] = useState(() =>
    typeof window === "undefined" ? 0 : window.innerWidth,
  );
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

export default function App() {
  const pendingConfirmId = useStore((s) => s.pendingConfirmModelId);
  const models = useStore((s) => s.models);
  const activeModel = useStore((s) => s.activeModel);
  const hasMessages = useStore((s) => s.messages.length > 0);
  const storedWidth = useStore((s) => s.panelWidth);
  const collapsed = useStore((s) => s.panelCollapsed);
  const componentOpen = useStore((s) => s.componentGuid !== null);
  const explanationOpen = useStore((s) => s.explanation !== null);
  const viewportWidth = useViewportWidth();
  const [resetOpen, setResetOpen] = useState(false);

  useEffect(() => {
    void controller.bootstrap();
  }, []);

  // The component panel docks immediately left of the chat panel — or, with the
  // explanation card open, left of the whole fixed right-side column. One CSS
  // variable keeps that in CSS rather than duplicating layout math, and the
  // viewer's obstruction below is derived from the very same number, so there
  // is never a second hard-coded set of measurements (task26 §3).
  const chatWidth = explanationOpen
    ? explanationColumnWidthPx(viewportWidth, componentOpen)
    : collapsed
      ? COLLAPSED_CHAT_WIDTH
      : effectivePanelWidth(storedWidth, componentOpen);

  // The viewer's camera-framing must center within the region actually left
  // unobstructed by the floating panels (task19 §2) — reuses this same live
  // chat width/component-open state as the single source of truth, never a
  // separate hard-coded copy in the viewer.
  useEffect(() => {
    controller.viewer.setViewportObstruction(effectiveViewportObstructionPx(chatWidth, componentOpen));
  }, [chatWidth, componentOpen]);

  const pendingModel = models.find((m) => m.source_model_id === pendingConfirmId) ?? null;
  const isSwitch = activeModel !== null && activeModel.source_model_id !== pendingConfirmId;

  const onResetApp = () => {
    if (hasMessages || activeModel) setResetOpen(true);
    else void controller.resetApp();
  };

  return (
    <div className="app" style={{ "--chat-w": `${chatWidth}px` } as React.CSSProperties}>
      <ViewerCanvas />
      <ViewerOverlay />
      <ViewerControls onResetApp={onResetApp} />
      <StatusReadout />
      <ComponentPanel />
      {explanationOpen ? (
        // Fixed stacked column: explanation above, chat below, 12 px apart
        // (task26 §3). No splitter, no saved preference, no reordering.
        <div
          className={`right-stack${collapsed ? " right-stack-collapsed" : ""}`}
          data-testid="right-stack"
        >
          <ExplanationPanel />
          <ChatPanel />
        </div>
      ) : (
        <ChatPanel />
      )}

      {pendingModel && (
        <ConfirmDialog
          title={isSwitch ? "Switch model?" : "Load model?"}
          body={
            isSwitch
              ? `Switching to “${pendingModel.display_name}” clears current results and selection, then loads the new model.`
              : `Load “${pendingModel.display_name}” into the viewer? This downloads the prepared 3D artifact.`
          }
          confirmLabel={isSwitch ? "Switch" : "Load"}
          onCancel={() => useStore.getState().setPendingConfirm(null)}
          onConfirm={() => {
            useStore.getState().setPendingConfirm(null);
            void controller.confirmAndLoadModel(pendingModel);
          }}
        />
      )}

      {resetOpen && (
        <ConfirmDialog
          title="Reset the app?"
          body="This clears the conversation, selection, and current model, and returns to the starting screen. The model cache is kept."
          confirmLabel="Reset"
          tone="danger"
          onCancel={() => setResetOpen(false)}
          onConfirm={() => {
            setResetOpen(false);
            void controller.resetApp();
          }}
        />
      )}
    </div>
  );
}
