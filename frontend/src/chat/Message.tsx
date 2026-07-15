import type { ChatMessage } from "../state/store";
import EvidenceDisclosure from "./EvidenceDisclosure";
import Markdown from "./Markdown";
import ModelCandidates from "./ModelCandidates";

// One conversation entry. User messages are compact right-aligned cards;
// assistant answers read like response records (document-like), per the design
// direction. Notices/errors get a quiet distinct treatment.
export default function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <div className="bubble-user">{message.content}</div>
      </div>
    );
  }

  const cls =
    message.kind === "error"
      ? "msg-assistant is-error"
      : message.kind === "notice"
        ? "msg-assistant is-notice"
        : message.kind === "clarification"
          ? "msg-assistant is-clarify"
          : "msg-assistant";

  return (
    <div className={`msg ${cls}`}>
      <div className="answer">
        {message.kind === "notice" ? (
          <p className="notice-text">{message.content}</p>
        ) : (
          <Markdown text={message.content} />
        )}
        {message.candidates && message.candidates.length > 0 && (
          <ModelCandidates candidates={message.candidates} />
        )}
        {message.evidence && <EvidenceDisclosure evidence={message.evidence} />}
      </div>
    </div>
  );
}
