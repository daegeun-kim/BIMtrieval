import { ResetIcon } from "./icons";

// Reset App, at the viewer's top-left (task14 §6).
//
// Deliberately separated from the viewer's Home/Fit control (bottom-left, in
// StatusReadout) and from Clear Chat (in the chat panel): the three do very
// different things, so they never sit adjacent to each other. This one is the
// only destructive-ish action of the three, so it carries a label rather than
// being an anonymous icon, and confirms before discarding a conversation.
export default function ViewerControls({ onResetApp }: { onResetApp: () => void }) {
  return (
    <div className="viewer-controls">
      <button
        className="reset-app-btn"
        onClick={onResetApp}
        title="Clear the conversation, selection, and model, and start over"
        aria-label="Reset app"
      >
        <ResetIcon size={14} />
        <span>Reset app</span>
      </button>
    </div>
  );
}
