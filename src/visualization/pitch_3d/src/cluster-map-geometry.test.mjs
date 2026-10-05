import assert from "node:assert/strict";
import test from "node:test";

import { clusterMapBounds, ellipseBoundary, mapPoint, PLOT } from "./cluster-map-geometry.ts";

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

test("2D GMM outline includes covariance projected from all three fitted dimensions", () => {
  const boundary = ellipseBoundary(data.clusters[0], 360);
  const ivbRadius = Math.max(...boundary.map(([ivb]) => Math.abs(ivb - 15)));
  const hbRadius = Math.max(...boundary.map(([, hb]) => Math.abs(hb - 10)));
  assert.ok(Math.abs(ivbRadius - Math.sqrt(5)) < 0.01);
  assert.ok(Math.abs(hbRadius - Math.sqrt(13)) < 0.01);
  assert.ok(boundary.every(([ivb, hb]) => Number.isFinite(ivb) && Number.isFinite(hb)));
});
