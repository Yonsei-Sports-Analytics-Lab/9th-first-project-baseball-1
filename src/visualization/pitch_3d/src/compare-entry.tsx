import React from "react";
import { createRoot, type Root } from "react-dom/client";
import Pitch3D from "./Pitch3D";
import type { PitchVisualizationData } from "./types";

const roots = new WeakMap<HTMLElement, Root>();

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
