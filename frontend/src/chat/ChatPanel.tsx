import { useRef } from "react";

import { controller } from "../state/controller";
import {
  PANEL_MAX_WIDTH,
  PANEL_MIN_WIDTH,
  PANEL_PAIRED_MAX_WIDTH,
  effectivePanelWidth,
  useStore,
} from "../state/store";
import ModelSelector from "../components/ModelSelector";
import { BroomIcon, CollapseIcon, ExpandIcon } from "../components/icons";
import Composer from "./Composer";
import MessageList from "./MessageList";

// Floating, resizable, collapsible conversation surface (spec_v006 §7.1). The
// left edge is a drag handle; collapsing hands the viewport back to the viewer
// and leaves a small accessible restore tab. Corner registration ticks in the
// header are the "measured drawing" signature.
//
// Clear Chat stays here (task14 §6); Reset App lives at the viewer's top-left,
// so the two are never adjacent and cannot be confused for one another.
export default function ChatPanel() {
  const storedWidth = useStore((s) => s.panelWidth);
  const collapsed = useStore((s) => s.panelCollapsed);
  const componentOpen = useStore((s) => s.componentGuid !== null);
  const setPanelWidth = useStore((s) => s.setPanelWidth);
  const toggleCollapsed = useStore((s) => s.togglePanelCollapsed);
  const hasMessages = useStore((s) => s.messages.length > 0);
  const dragging = useRef(false);

  // With the component panel open both panels take narrower defaults so the
  // model stays usable (task14 §5). The user's stored preference is preserved
  // and restored when the component panel closes.
  const width = effectivePanelWidth(storedWidth, componentOpen);
  const maxWidth = componentOpen ? PANEL_PAIRED_MAX_WIDTH : PANEL_MAX_WIDTH;

  const startResize = (e: React.PointerEvent) => {
    dragging.current = true;
    const startX = e.clientX;
    const startW = width;
    const onMove = (ev: PointerEvent) => {
      if (!dragging.current) return;
      // panel is anchored right, so dragging left (smaller clientX) widens it
      const next = startW + (startX - ev.clientX);
      setPanelWidth(Math.min(maxWidth, Math.max(PANEL_MIN_WIDTH, next)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  if (collapsed) {
    return (
      <button className="panel-restore" onClick={toggleCollapsed} aria-label="Open chat panel">
        <ExpandIcon size={18} />
      </button>
    );
  }

  return (
    <section className="panel" style={{ width }} aria-label="Conversation">
      <div className="panel-resizer" onPointerDown={startResize} role="separator" aria-orientation="vertical" />
      <div className="tick tick-tl" />
      <div className="tick tick-tr" />
      <header className="panel-head">
        <ModelSelector />
        <div className="head-actions">
          <button
            className="icon-btn"
            title="Clear chat (keeps the model and selection)"
            aria-label="Clear chat"
            onClick={() => void controller.clearChat()}
          >
            <BroomIcon size={16} />
          </button>
          <button
            className="icon-btn"
            title="Collapse panel"
            aria-label="Collapse panel"
            onClick={toggleCollapsed}
          >
            <CollapseIcon size={16} />
          </button>
        </div>
      </header>
      <MessageList />
      <Composer />
      {hasMessages && <div className="tick tick-bl" />}
    </section>
  );
}
