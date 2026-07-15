import { useRef } from "react";

import { controller } from "../state/controller";
import { PANEL_MAX_WIDTH, PANEL_MIN_WIDTH, useStore } from "../state/store";
import ModelSelector from "../components/ModelSelector";
import { BroomIcon, CollapseIcon, ExpandIcon, ResetIcon } from "../components/icons";
import Composer from "./Composer";
import MessageList from "./MessageList";

// Floating, resizable, collapsible conversation surface (spec_v006 §7.1). The
// left edge is a drag handle; collapsing hands the viewport back to the viewer
// and leaves a small accessible restore tab. Corner registration ticks in the
// header are the "measured drawing" signature.
export default function ChatPanel({ onResetApp }: { onResetApp: () => void }) {
  const width = useStore((s) => s.panelWidth);
  const collapsed = useStore((s) => s.panelCollapsed);
  const setPanelWidth = useStore((s) => s.setPanelWidth);
  const toggleCollapsed = useStore((s) => s.togglePanelCollapsed);
  const hasMessages = useStore((s) => s.messages.length > 0);
  const dragging = useRef(false);

  const startResize = (e: React.PointerEvent) => {
    dragging.current = true;
    const startX = e.clientX;
    const startW = width;
    const onMove = (ev: PointerEvent) => {
      if (!dragging.current) return;
      // panel is anchored right, so dragging left (smaller clientX) widens it
      const next = startW + (startX - ev.clientX);
      setPanelWidth(Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, next)));
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
          <button className="icon-btn" title="Reset app" aria-label="Reset app" onClick={onResetApp}>
            <ResetIcon size={16} />
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
