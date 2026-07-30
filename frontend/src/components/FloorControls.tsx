import { controller } from "../state/controller";
import { useStore } from "../state/store";

// Floor-plan mode control (tasks/task28.md §1.1), directly below Reset app.
//
// A compact vertical stack: 3D, then one button per LOGICAL floor band the
// backend's read-only `/floors` contract reported — never one per raw
// IfcBuildingStorey, and never grouped, ordered, or labelled from a storey name.
// Source storey names appear only in the tooltip / accessible description.
//
// Deliberately NOT a tree, storey browser, visibility checklist, clipping-plane
// editor, or saved-view manager: these buttons are the only new main-viewer
// control this task adds.

/** Tooltip + accessible description for one floor button. */
function describe(label: string, storeyNames: string[], reason: string | null): string {
  if (reason) return `${label} — ${reason}`;
  if (storeyNames.length === 0) return label;
  return `${label} — IFC storeys: ${storeyNames.join(", ")}`;
}

export default function FloorControls() {
  const loadPhase = useStore((s) => s.loadPhase);
  const available = useStore((s) => s.floorsAvailable);
  const options = useStore((s) => s.floorOptions);
  const mode = useStore((s) => s.floorMode);
  const activeBand = useStore((s) => s.floorBandIndex);
  const notice = useStore((s) => s.floorNotice);

  // The control exists only once a model with usable logical floors is ready.
  // With no usable floor data it is omitted entirely and the viewer is unchanged.
  if (loadPhase !== "ready" || !available || options.length === 0) return null;

  const is3d = mode === "3d";

  return (
    <div className="floor-controls" data-testid="floor-controls">
      <div className="floor-buttons" role="group" aria-label="Viewer floor plan">
        <button
          type="button"
          className={`floor-btn${is3d ? " floor-btn-active" : ""}`}
          aria-pressed={is3d}
          title="Return to the 3D view"
          onClick={() => void controller.selectFloor(null)}
        >
          3D
        </button>
        {options.map((option) => {
          const active = mode === "plan" && activeBand === option.bandIndex;
          return (
            <button
              key={option.bandIndex}
              type="button"
              className={`floor-btn${active ? " floor-btn-active" : ""}`}
              aria-pressed={active}
              disabled={!option.enabled}
              title={describe(option.label, option.storeyNames, option.reason)}
              onClick={() => void controller.selectFloor(option.bandIndex)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {notice && (
        <p className="floor-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
