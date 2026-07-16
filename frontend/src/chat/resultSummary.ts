// Compact class summary for chat results (tasks/task14.md §4).
//
// Turns the backend's exact per-IFC-class counts into a short readable line —
// "5 doors, 3 windows" — instead of listing every retrieved component.

/**
 * Display labels for IFC classes. Explicit rather than generic so the common
 * cases read naturally.
 *
 * `IfcWall` and `IfcWallStandardCase` deliberately share the label "wall": they
 * are both walls, the backend counts them as one set when you ask for walls
 * (spec_v003 §19.2), and "648 walls, 232 wall standard cases" would be a
 * distinction without a difference to the reader. Counts for classes that share
 * a label are merged.
 */
const CLASS_LABELS: Record<string, string> = {
  ifcwall: "wall",
  ifcwallstandardcase: "wall",
  ifcwallelementedcase: "wall",
  ifcdoor: "door",
  ifcwindow: "window",
  ifcslab: "slab",
  ifcroof: "roof",
  ifccolumn: "column",
  ifcbeam: "beam",
  ifcstair: "stair",
  ifcstairflight: "stair flight",
  ifcrailing: "railing",
  ifccovering: "covering",
  ifcspace: "space",
  ifcbuildingstorey: "storey",
  ifcfurnishingelement: "furnishing",
  ifcflowterminal: "terminal",
  ifcbuildingelementproxy: "element",
  ifcmember: "member",
  ifcplate: "plate",
  ifcopeningelement: "opening",
};

export interface ClassSummaryItem {
  label: string;
  count: number;
}

/** "IfcFurnishingElement" -> "furnishing element" for classes not in the map. */
function humanize(ifcClass: string): string {
  const stripped = ifcClass.replace(/^Ifc/i, "");
  const spaced = stripped.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
  return spaced.toLowerCase() || ifcClass.toLowerCase();
}

function labelFor(ifcClass: string): string {
  return CLASS_LABELS[ifcClass.trim().toLowerCase()] ?? humanize(ifcClass);
}

function plural(label: string, count: number): string {
  if (count === 1) return label;
  if (/(s|x|z|ch|sh)$/.test(label)) return `${label}es`;
  if (/[^aeiou]y$/.test(label)) return `${label.slice(0, -1)}ies`;
  return `${label}s`;
}

/** Merge counts by display label, ordered by count desc then label asc. */
export function summarizeClassCounts(
  counts: Record<string, number> | null | undefined,
): ClassSummaryItem[] {
  if (!counts) return [];
  const merged = new Map<string, number>();
  for (const [ifcClass, n] of Object.entries(counts)) {
    if (!n) continue;
    const label = labelFor(ifcClass);
    merged.set(label, (merged.get(label) ?? 0) + n);
  }
  return [...merged.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

/** "5 doors, 3 windows" */
export function formatClassSummary(counts: Record<string, number> | null | undefined): string {
  return summarizeClassCounts(counts)
    .map((i) => `${i.count} ${plural(i.label, i.count)}`)
    .join(", ");
}
