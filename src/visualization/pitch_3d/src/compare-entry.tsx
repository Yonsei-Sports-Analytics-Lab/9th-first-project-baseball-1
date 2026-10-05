import React from "react";
import { createRoot, type Root } from "react-dom/client";
import Pitch3D from "./Pitch3D";
import ClusterMap2D from "./ClusterMap2D";
import type { ClusterMapData, PitchVisualizationData } from "./types";

const roots = new WeakMap<HTMLElement, Root>();
const clusterRoots = new WeakMap<HTMLElement, Root>();

export function mountComparison(element: HTMLElement, input: PitchVisualizationData, similar: PitchVisualizationData) {
  let root = roots.get(element);
  if (!root) {
    root = createRoot(element);
    roots.set(element, root);
  }
  root.render(<Pitch3D data={input} comparisonData={similar} />);
}

export function unmountComparison(element: HTMLElement) {
  const root = roots.get(element);
  if (root) {
    root.unmount();
    roots.delete(element);
  }
}

export function mountClusterMap(element: HTMLElement, data: ClusterMapData, names: { input: string; similar: string }) {
  let root = clusterRoots.get(element);
  if (!root) {
    root = createRoot(element);
    clusterRoots.set(element, root);
  }
  root.render(<ClusterMap2D data={data} names={names} />);
}

export function unmountClusterMap(element: HTMLElement) {
  const root = clusterRoots.get(element);
  if (root) {
    root.unmount();
    clusterRoots.delete(element);
  }
}
