// Viewer highlight materials for the semantic roles the backend returns
// (spec_v006 §11.3) plus manual selection, which stays visually distinct from
// query-result roles. Colors are derived from the "measured drawing" palette:
// blueprint blue for primary matches, ochre for relationship context, teal for
// the user's own manual picks, and a translucent ghost for dimmed non-results.
import * as THREE from "three";
import type * as FRAGS from "@thatopen/fragments";

export type RoleMaterial = FRAGS.MaterialDefinition;

export const PRIMARY_MATERIAL: RoleMaterial = {
  color: new THREE.Color("#1f6feb"),
  opacity: 1,
  transparent: false,
  renderedFaces: 0 as FRAGS.RenderedFaces,
};

export const CONTEXT_MATERIAL: RoleMaterial = {
  color: new THREE.Color("#e8a94f"),
  opacity: 0.92,
  transparent: true,
  renderedFaces: 0 as FRAGS.RenderedFaces,
};

export const MANUAL_MATERIAL: RoleMaterial = {
  color: new THREE.Color("#0fb5c9"),
  opacity: 1,
  transparent: false,
  renderedFaces: 0 as FRAGS.RenderedFaces,
};

// Applied to the whole model first so non-results recede while keeping spatial
// context; role materials are then layered over the relevant items.
export const DIM_MATERIAL: RoleMaterial = {
  color: new THREE.Color("#c7ced6"),
  opacity: 0.22,
  transparent: true,
  renderedFaces: 0 as FRAGS.RenderedFaces,
};
