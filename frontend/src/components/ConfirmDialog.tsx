// Lightweight confirmation used before loading/switching a model and before a
// destructive Reset App (spec_v006 §8.2, §13.2).
export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  tone = "default",
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <div className="dialog-scrim" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="dialog-title">{title}</h2>
        <p className="dialog-body">{body}</p>
        <div className="dialog-actions">
          <button className="btn-ghost" onClick={onCancel} autoFocus>
            Cancel
          </button>
          <button className={tone === "danger" ? "btn-danger" : "btn-primary"} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
