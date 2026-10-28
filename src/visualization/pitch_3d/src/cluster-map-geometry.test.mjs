import assert from "node:assert/strict";
import test from "node:test";

import { clusterMapBounds, mapPoint, PLOT } from "./cluster-map-geometry.ts";

const data = {
  points: [[10, 5, -80, 0], [20, 15, 90, 1]],
  pitchers: [{ point: [15, 10, 50], cluster: 0 }],
  clusters: [{ id: 0, center: [15, 10, 50], shape_matrix: [[2, 0, 1], [0, 3, 2], [0, 0, 4]] }],
};

test("IVB-HB map shows each pitcher mean as one point and never uses arm angle as an axis", () => {
  const bounds = clusterMapBounds(data);
  assert.deepEqual(mapPoint([15, 10, 0], bounds), mapPoint([15, 10, 90], bounds));
  assert.ok(mapPoint([20, 15, 60], bounds)[0] > mapPoint([10, 5, 40], bounds)[0]);
  assert.ok(mapPoint([20, 15, 60], bounds)[1] < mapPoint([10, 5, 40], bounds)[1]);
  assert.ok(mapPoint([15, 10, 50], bounds)[0] >= PLOT.left);
  assert.ok(clusterMapBounds(data, 0)[0][1] - clusterMapBounds(data, 0)[0][0] < bounds[0][1] - bounds[0][0]);
  const focused = clusterMapBounds({ ...data, pitchers: [...data.pitchers, { point: [30, 30, 10], cluster: 1 }] }, 0);
  assert.ok(focused[0][1] > 30 && focused[1][1] > 30, "both pitcher points remain visible when selecting a cluster");
});

test("scatter plot bounds use observed sample and pitcher points, not density outlines", () => {
  const bounds = clusterMapBounds(data);
  const distantRegion = { ...data, clusters: [{ ...data.clusters[0], center: [500, 500, 50], shape_matrix: [[500, 0, 0], [0, 500, 0], [0, 0, 500]] }] };
  assert.deepEqual(clusterMapBounds(distantRegion), bounds);
});
