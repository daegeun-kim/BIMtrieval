import { useState } from "react";

import { controller } from "../state/controller";
import type { EntityCitation } from "../api/types";
import type { EvidenceView } from "../state/store";

// Compact evidence ledger under an answer (spec_v006 §12.2), collapsed by
// default. Route/basis and bounded counts are set in mono to read as a technical
// readout. Entity references are clickable and center the object without an LLM
// call (spec_v006 §11.4).
function CitationList({ items, label }: { items: EntityCitation[]; label: string }) {
  if (items.length === 0) return null;
  return (
    <div className="ev-row">
      <span className="ev-key">{label}</span>
      <span className="ev-cites">
        {items.map((c) => (
          <button
            key={`${c.role}-${c.entityId}`}
            className={`cite cite-${c.role}`}
            title={c.globalId}
            onClick={() => void controller.focusCitation(c)}
          >
            {c.name || c.ifcClass}
          </button>
        ))}
      </span>
    </div>
  );
}

export default function EvidenceDisclosure({ evidence }: { evidence: EvidenceView }) {
  const [open, setOpen] = useState(false);
  const counts: string[] = [];
  if (evidence.sqlCount != null) counts.push(`sql ${evidence.sqlCount}`);
  if (evidence.ragCount != null) counts.push(`rag ${evidence.ragCount}`);
  if (evidence.relCount != null) counts.push(`rel ${evidence.relCount}`);

  return (
    <div className="evidence">
      <button className="ev-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="ev-caret" data-open={open}>
          ▸
        </span>
        <span className="ev-route">{evidence.route}</span>
        <span className="ev-basis">{evidence.answerBasis.replace(/_/g, " ")}</span>
        {counts.length > 0 && <span className="ev-counts">{counts.join(" · ")}</span>}
      </button>
      {open && (
        <div className="ev-body">
          <CitationList items={evidence.primaries} label="primary" />
          <CitationList items={evidence.contexts} label="context" />
          {evidence.relationships.length > 0 && (
            <div className="ev-row">
              <span className="ev-key">relationships</span>
              <span className="ev-mono">
                {evidence.relationships.map((r) => r.ifc_class).join(", ")}
              </span>
            </div>
          )}
          {evidence.notes.map((n, i) => (
            <div className="ev-note" key={`n${i}`}>
              {n}
            </div>
          ))}
          {evidence.warnings.map((w, i) => (
            <div className="ev-warn" key={`w${i}`}>
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
