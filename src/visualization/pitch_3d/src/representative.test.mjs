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

test("selects one real median-like pitch per type, not an averaged synthetic line", () => {
  const rows = [pitch("low", "FF", -2), pitch("middle", "FF", 0), pitch("high", "FF", 2), pitch("slider", "SL", 3)];
  const selected = representativeTrajectories(rows);
  assert.deepEqual(selected.map(({ id }) => id), ["middle", "slider"]);
  assert.strictEqual(selected[0], rows[1]);
});

test("ignores trajectories without enough points", () => {
  const malformed = { ...pitch("bad", "FF", 0), points: [] };
  assert.deepEqual(representativeTrajectories([malformed, pitch("good", "FF", 1)]).map(({ id }) => id), ["good"]);
});
