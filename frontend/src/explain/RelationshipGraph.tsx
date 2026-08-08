import type { ExplanationGraph, ExplanationGraphNode, ExplanationGroup } from "../api/types";
import { formatCount, graphNodeAsGroup } from "./explanation";

// The grouped relationship diagram (Task 29 §5.4).
//
// Deterministic layout only. The backend already decided which nodes and edges
// exist, how they group, and whether the diagram qualifies at all; this file
// places them. There is no force simulation, no animation, no post-load jitter,
// and no charting or graph dependency — an SVG edge layer with real <button>
// nodes above it, so focus, aria-pressed and disabled come from the platform
// rather than from re-implemented ARIA.
//
// Edges are drawn from the recorded IFC direction (source is always the relating
// side), and a node is interactive only when the backend marked it selectable.

/** Fixed geometry. Chosen so 24 nodes still fit the card's scroll area. */
const NODE_W = 132;
const NODE_H = 46;
const COL_GAP = 96;
const ROW_GAP = 14;
const PAD = 8;
/** Endpoint nodes per column, so a wide result wraps instead of shrinking. */
const COL_CAPACITY = 8;

type Placed = { node: ExplanationGraphNode; x: number; y: number };

/**
 * Seed at the left, endpoint groups in fixed-capacity columns to its right.
 *
 * Derived purely from the backend's node order, which is itself deterministic
 * (seed first, then largest group first), so the same payload always lays out
 * identically.
 */
function layout(graph: ExplanationGraph): { placed: Placed[]; width: number; height: number } {
  const nodes = graph.nodes ?? [];
  const seeds = nodes.filter((n) => n.role === "seed");
  const endpoints = nodes.filter((n) => n.role !== "seed");

  const columns: ExplanationGraphNode[][] = [];
  for (let i = 0; i < endpoints.length; i += COL_CAPACITY) {
    columns.push(endpoints.slice(i, i + COL_CAPACITY));
  }
  const rows = Math.max(seeds.length, ...columns.map((c) => c.length), 1);
  const height = PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP;
  const width = PAD * 2 + (columns.length + 1) * NODE_W + columns.length * COL_GAP;

  const place = (column: ExplanationGraphNode[], columnIndex: number): Placed[] => {
    const blockH = column.length * NODE_H + (column.length - 1) * ROW_GAP;
    const top = (height - blockH) / 2;
    return column.map((node, row) => ({
      node,
      x: PAD + columnIndex * (NODE_W + COL_GAP),
      y: top + row * (NODE_H + ROW_GAP),
    }));
  };

  return {
    placed: [
      ...place(seeds, 0),
      ...columns.flatMap((column, index) => place(column, index + 1)),
    ],
    width,
    height,
  };
}

/** Right edge of the source box to the left edge of the target box. */
function edgePath(from: Placed, to: Placed): string {
  const forward = to.x >= from.x;
  const x1 = forward ? from.x + NODE_W : from.x;
  const x2 = forward ? to.x : to.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const y2 = to.y + NODE_H / 2;
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

export default function RelationshipGraph({
  graph,
  activeKey,
  onSelect,
}: {
  graph: ExplanationGraph;
  activeKey: string | null;
  onSelect: (group: ExplanationGroup) => void;
}) {
  const { placed, width, height } = layout(graph);
  const byId = new Map(placed.map((p) => [p.node.id, p]));
  const edges = graph.edges ?? [];

  return (
    <div className="ex-graph" data-testid="ex-graph">
      {/* The same nodes and edges in prose, for assistive technology. Supplied
          by the backend so it can never describe a different topology. */}
      <p className="ex-sr-only" data-testid="ex-graph-description">
        {graph.description}
      </p>

      <div className="ex-graph-scroll">
        <div className="ex-graph-canvas" data-testid="ex-graph-canvas" style={{ width, height }}>
          <svg
            className="ex-graph-edges"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              <marker
                id="ex-graph-arrow"
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <path d="M 0 0 L 7 3.5 L 0 7 z" className="ex-graph-arrowhead" />
              </marker>
            </defs>
            {edges.map((edge) => {
              const from = byId.get(edge.source_node_id);
              const to = byId.get(edge.target_node_id);
              if (!from || !to) return null;
              return (
                <path
                  key={edge.id}
                  className="ex-graph-edge"
                  d={edgePath(from, to)}
                  markerEnd="url(#ex-graph-arrow)"
                />
              );
            })}
          </svg>

          {placed.map(({ node, x, y }) => {
            const active = activeKey === node.id;
            const style = { left: x, top: y, width: NODE_W, height: NODE_H };
            const body = (
              <>
                <span className="ex-graph-node-label">{node.label}</span>
                <span className="ex-graph-node-count">
                  {formatCount(node.entity_count ?? 0)}
                  {node.role === "seed" ? " · subject" : " object(s)"}
                </span>
              </>
            );
            if (!node.selectable) {
              return (
                <div
                  key={node.id}
                  className={`ex-graph-node ex-graph-node-${node.role}`}
                  style={style}
                  title={
                    node.role === "seed"
                      ? "The subject this question traced connections from"
                      : "No highlightable object identities for this group"
                  }
                >
                  {body}
                </div>
              );
            }
            return (
              <button
                key={node.id}
                type="button"
                className={`ex-graph-node ex-graph-node-${node.role}${
                  active ? " ex-graph-node-on" : ""
                }`}
                style={style}
                aria-pressed={active}
                aria-label={`${node.label}, ${formatCount(node.entity_count ?? 0)} objects`}
                title={`Highlight only ${node.label}`}
                onClick={() => onSelect(graphNodeAsGroup(node))}
              >
                {body}
              </button>
            );
          })}
        </div>
      </div>

      {/* Edge meanings, counts and direction as text: readable at any width, and
          the accessible reading of the arrows above. */}
      <ul className="ex-graph-legend" aria-label="Relationship connections">
        {edges.map((edge) => {
          const from = byId.get(edge.source_node_id)?.node.label ?? edge.source_node_id;
          const to = byId.get(edge.target_node_id)?.node.label ?? edge.target_node_id;
          return (
            <li className="ex-graph-legend-row" key={edge.id}>
              <span className="ex-graph-legend-path">
                {from} <span aria-hidden="true">→</span>
                <span className="ex-sr-only"> to </span> {to}
              </span>
              <span className="ex-graph-legend-meaning">{edge.label}</span>
              <span className="ex-graph-legend-count">
                {formatCount(edge.connection_count ?? 0)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
