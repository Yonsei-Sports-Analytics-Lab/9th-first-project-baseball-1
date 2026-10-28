import assert from "node:assert/strict";
import { test } from "node:test";
import { representativeTrajectories } from "./representative.ts";

function pitch(id, type, x, speed = 90) {
  return {
    id, pitch_type: type, pitch_name: type, release_speed: speed,
    method: "statcast", flight_time: 0.4,
    points: [0, 1, 2].map((z) => ({ x, y: 4, z, time: z / 100, speed_mph: speed })),
  };
}

test("selects an actual pitch in the most frequent sampled plate-location bin", () => {
  const rows = [
    pitch("low", "FF", -2), pitch("middle", "FF", 0),
    pitch("mode-a", "FF", 2.01), pitch("mode-b", "FF", 2.04), pitch("mode-center", "FF", 2.08),
    pitch("slider", "SL", 3),
  ];
  const selected = representativeTrajectories(rows);
  assert.deepEqual(selected.map(({ id }) => id), ["mode-center", "slider"]);
  assert.strictEqual(selected[0], rows[4]);
});

test("full-season modal plate location overrides the small sampled distribution", () => {
  const rows = [pitch("season-mode", "FF", 1.12), pitch("sample-a", "FF", 2.01), pitch("sample-b", "FF", 2.04)];
  const selected = representativeTrajectories(rows, [{ code: "FF", modal_plate_x: -1.125, modal_plate_z: 4 }]);
  assert.strictEqual(selected[0], rows[0]);
});

test("ignores trajectories without enough points", () => {
  const malformed = { ...pitch("bad", "FF", 0), points: [] };
  assert.deepEqual(representativeTrajectories([malformed, pitch("good", "FF", 1)]).map(({ id }) => id), ["good"]);
});
