import { controller } from "../state/controller";
import { useStore } from "../state/store";
import {
  VISUALIZATION_MODE_LABELS,
  VISUALIZATION_MODE_ORDER,
} from "../viewer/viewerCustomization";

// Fine | Standard | Fast — the visualization-quality control (Task 31
// §2.1), sitting in the existing bottom-left readout beside Fit.
//
// This is a QUALITY choice the user makes, not the removed Task 18
// automatic/manual performance-profile control: nothing here measures frame
// time, nothing switches on the user's behalf, and there is no "automatic"
// option. It only asks the controller to change the mode; the imperative scene
// work lives in ViewerAdapter.
//
// Rendered as a radio group rather than three toggle buttons so the three
// options are announced as one exclusive choice, and so arrow keys move between
// them the way a segmented control should.
export default function VisualizationModeControl() {
  const mode = useStore((s) => s.visualizationMode);

  return (
    <div className="vis-modes" role="radiogroup" aria-label="Visualization quality">
      {VISUALIZATION_MODE_ORDER.map((option) => {
        const active = option === mode;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            // Only the selected option stays in the tab order; arrow keys move
            // within the group, which is the expected radio-group behavior.
            tabIndex={active ? 0 : -1}
            className={`vis-mode${active ? " vis-mode-on" : ""}`}
            onClick={() => void controller.setVisualizationMode(option)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              e.preventDefault();
              const index = VISUALIZATION_MODE_ORDER.indexOf(option);
              const step = e.key === "ArrowRight" ? 1 : -1;
              const count = VISUALIZATION_MODE_ORDER.length;
              const nextIndex = (index + step + count) % count;
              void controller.setVisualizationMode(VISUALIZATION_MODE_ORDER[nextIndex]!);
              // Focus follows the selection, as it does in a native radio group:
              // otherwise a second arrow press would move from the stale option.
              const siblings = e.currentTarget.parentElement?.querySelectorAll<HTMLElement>(
                '[role="radio"]',
              );
              siblings?.[nextIndex]?.focus();
            }}
          >
            {VISUALIZATION_MODE_LABELS[option]}
          </button>
        );
      })}
    </div>
  );
}
