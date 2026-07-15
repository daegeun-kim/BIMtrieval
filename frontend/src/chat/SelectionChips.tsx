import { controller } from "../state/controller";
import { useStore } from "../state/store";
import { CloseIcon } from "../components/icons";

// Compact removable chips for the up-to-five manual viewer selection
// (spec_v006 §11.2). Names come from the deterministic resolver; the raw
// GlobalId (mono) is the fallback and the accessible identity.
export default function SelectionChips() {
  const guids = useStore((s) => s.manualGuids);
  const resolved = useStore((s) => s.resolvedChips);
  const notice = useStore((s) => s.selectionNotice);

  if (guids.length === 0 && !notice) return null;

  return (
    <div className="chips" aria-label="Selected objects">
      {guids.map((g) => {
        const ent = resolved[g];
        const label = ent?.name || ent?.ifc_class || g;
        return (
          <span className="chip" key={g} title={g}>
            <span className="chip-label">{label}</span>
            <button
              className="chip-x"
              aria-label={`Remove ${label} from selection`}
              onClick={() => controller.removeChip(g)}
            >
              <CloseIcon size={12} />
            </button>
          </span>
        );
      })}
      {notice && (
        <span className="chip-notice" role="status">
          {notice}
        </span>
      )}
    </div>
  );
}
