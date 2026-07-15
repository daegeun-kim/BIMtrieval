import { useRef, useState } from "react";

import { controller } from "../state/controller";
import { useStore } from "../state/store";
import { SendIcon, StopIcon } from "../components/icons";
import SelectionChips from "./SelectionChips";

// Bottom-anchored composer (spec_v006 §12.1): Enter submits, Shift+Enter inserts
// a newline, blank input is rejected, a pending request can be canceled, and a
// retryable failure offers one explicit Retry.
export default function Composer() {
  const [text, setText] = useState("");
  const pending = useStore((s) => s.pending);
  const retryQuestion = useStore((s) => s.retryQuestion);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const canSend = text.trim().length > 0 && !pending;

  const submit = () => {
    if (!canSend) return;
    void controller.submitQuestion(text);
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="composer">
      <SelectionChips />
      {retryQuestion && !pending && (
        <div className="retry-row">
          <span className="retry-text">That request didn't go through.</span>
          <button className="btn-retry" onClick={() => controller.retry()}>
            Retry
          </button>
        </div>
      )}
      <div className="composer-input">
        <textarea
          ref={taRef}
          value={text}
          onChange={autoGrow}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Ask about the model…"
          aria-label="Ask a question about the model"
          disabled={pending}
        />
        {pending ? (
          <button className="btn-send is-stop" onClick={() => controller.cancelQuery()} aria-label="Cancel request">
            <StopIcon size={16} />
          </button>
        ) : (
          <button className="btn-send" onClick={submit} disabled={!canSend} aria-label="Send question">
            <SendIcon size={16} />
          </button>
        )}
      </div>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
    </div>
  );
}
