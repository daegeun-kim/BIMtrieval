import { useEffect, useRef } from "react";

import { useStore } from "../state/store";
import Message from "./Message";

// Scrollable history with sensible auto-scroll: sticks to the bottom only when
// the user is already near it, so reading older messages isn't interrupted.
export default function MessageList() {
  const messages = useStore((s) => s.messages);
  const pending = useStore((s) => s.pending);
  const activeModel = useStore((s) => s.activeModel);
  const ref = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, pending]);

  return (
    <div className="messages" ref={ref}>
      {messages.length === 0 && (
        <div className="empty-hint">
          <p className="empty-title">Ask about the building model</p>
          <p className="empty-sub">
            {activeModel
              ? "Select objects in the view to add them as context, then ask a question."
              : "Choose a model above to load it, or ask a general question to get started."}
          </p>
        </div>
      )}
      {messages.map((m) => (
        <Message key={m.id} message={m} />
      ))}
      {pending && (
        <div className="msg msg-assistant">
          <div className="pending" aria-live="polite">
            <span className="dot" />
            <span className="dot" />
            <span className="dot" />
            <span className="pending-text">Working…</span>
          </div>
        </div>
      )}
    </div>
  );
}
