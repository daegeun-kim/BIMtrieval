import type { DetailValue, EntityDetailsResponse, HighlightScope } from "../api/types";
import { controller } from "../state/controller";
import { useStore } from "../state/store";
import ComponentPreview from "./ComponentPreview";

// Floating component-detail panel, immediately left of the chat panel
// (task14 §5). Read-only and truthful: fields the model does not have are
// omitted rather than shown empty, and the type/family actions are disabled
// with a concrete reason instead of guessing. Opening the panel and using its
// buttons never calls an LLM or touches the conversation.

const SCOPES: { key: HighlightScope; label: string }[] = [
  { key: "instance", label: "Instance" },
  { key: "type", label: "Same type" },
  { key: "family", label: "Same family" },
];

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="cp-row">
      <span className="cp-key">{label}</span>
      <span className="cp-val">{value}</span>
    </div>
  );
}

/** A group of allowlisted values; renders nothing when the model has none. */
function ValueGroup({ title, values }: { title: string; values: DetailValue[] }) {
  if (values.length === 0) return null;
  return (
    <section className="cp-group">
      <h4 className="cp-group-title">{title}</h4>
      {values.map((v) => (
        <div className="cp-row" key={`${v.source_set ?? ""}.${v.name}`}>
          <span className="cp-key" title={v.source_set ?? undefined}>
            {v.name}
          </span>
          <span className="cp-val">
            {v.value}
            {v.unit ? <span className="cp-unit"> {v.unit}</span> : null}
          </span>
        </div>
      ))}
    </section>
  );
}

function Details({ details }: { details: EntityDetailsResponse }) {
  const i = details.instance;
  const materials = i.materials ?? [];
  return (
    <div className="cp-details">
      <section className="cp-group">
        <h4 className="cp-group-title">Instance</h4>
        {/* The IFC class is already the panel header's subtitle — not repeated here. */}
        {i.predefined_type ? <Row label="Predefined type" value={i.predefined_type} /> : null}
        {i.object_type ? <Row label="Object type" value={i.object_type} /> : null}
        {i.tag ? <Row label="Tag" value={i.tag} /> : null}
        {i.storey_name ? <Row label="Storey" value={i.storey_name} /> : null}
        {typeof i.elevation === "number" ? <Row label="Elevation" value={String(i.elevation)} /> : null}
        {i.description ? <Row label="Description" value={i.description} /> : null}
        <Row label="GlobalId" value={i.global_id} />
      </section>

      {/* Type/family appear ONLY when the IFC explicitly supplied them. */}
      {details.type ? (
        <section className="cp-group">
          <h4 className="cp-group-title">Type</h4>
          {details.type.name ? <Row label="Name" value={details.type.name} /> : null}
          {details.type.ifc_class ? <Row label="Class" value={details.type.ifc_class} /> : null}
          {details.type.predefined_type ? (
            <Row label="Predefined type" value={details.type.predefined_type} />
          ) : null}
        </section>
      ) : null}

      {details.family ? (
        <section className="cp-group">
          <h4 className="cp-group-title">Family</h4>
          <Row label="Value" value={details.family.value} />
          <Row
            label="Source"
            value={`${details.family.property_set} · ${details.family.property_name}`}
          />
        </section>
      ) : null}

      {materials.length > 0 ? (
        <section className="cp-group">
          <h4 className="cp-group-title">Materials</h4>
          <div className="cp-tags">
            {materials.map((m) => (
              <span className="cp-tag" key={m}>
                {m}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <ValueGroup title="Dimensions & quantities" values={details.instance.quantities ?? []} />
      <ValueGroup title="Properties" values={details.instance.properties ?? []} />
    </div>
  );
}

export default function ComponentPanel() {
  const guid = useStore((s) => s.componentGuid);
  const details = useStore((s) => s.componentDetails);
  const loading = useStore((s) => s.componentLoading);
  const error = useStore((s) => s.componentError);
  const scope = useStore((s) => s.componentScope);
  const notice = useStore((s) => s.componentGroupNotice);
  const chatCollapsed = useStore((s) => s.panelCollapsed);

  if (!guid) return null;

  const availability = details?.availability;
  const enabled: Record<HighlightScope, boolean> = {
    instance: Boolean(details),
    type: Boolean(availability?.same_type),
    family: Boolean(availability?.same_family),
  };
  const reasons: Partial<Record<HighlightScope, string>> = {
    type: availability?.type_unavailable_reason ?? undefined,
    family: availability?.family_unavailable_reason ?? undefined,
  };
  const disabledReasons = SCOPES.filter((s) => !enabled[s.key] && reasons[s.key]).map(
    (s) => reasons[s.key]!,
  );

  const title = details?.instance.name ?? "Component";
  const subtitle = details?.instance.ifc_class ?? guid;

  return (
    <aside
      className={`component-panel${chatCollapsed ? " component-panel-solo" : ""}`}
      aria-label="Component details"
    >
      <header className="cp-head">
        <div className="cp-head-text">
          <h3 className="cp-title" title={title}>
            {title}
          </h3>
          <p className="cp-sub">{subtitle}</p>
        </div>
        <button
          className="cp-close"
          onClick={() => controller.closeComponent()}
          aria-label="Close component details"
          title="Close"
        >
          ×
        </button>
      </header>

      <ComponentPreview guid={guid} />

      <div className="cp-actions" role="group" aria-label="Highlight matching objects">
        {SCOPES.map((s) => (
          <button
            key={s.key}
            className={`cp-action${scope === s.key ? " cp-action-on" : ""}`}
            disabled={!enabled[s.key]}
            title={enabled[s.key] ? `Highlight ${s.label.toLowerCase()}` : reasons[s.key]}
            onClick={() => void controller.applyGroupScope(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {notice ? (
        <p className="cp-notice" aria-live="polite">
          {notice}
        </p>
      ) : null}
      {/* State the model's limitation plainly rather than leaving dead buttons. */}
      {disabledReasons.length > 0 ? (
        <p className="cp-reason">{disabledReasons.join(" ")}</p>
      ) : null}

      <div className="cp-body">
        {loading ? <p className="cp-status">Loading details…</p> : null}
        {error ? <p className="cp-status cp-status-err">{error}</p> : null}
        {details ? <Details details={details} /> : null}
      </div>
    </aside>
  );
}
