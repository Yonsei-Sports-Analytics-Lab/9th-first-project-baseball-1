import assert from "node:assert/strict";
import test from "node:test";

import { meetsMinimumUsage, visiblePitchTypes } from "./pitch-filter.ts";

const data = {
  season_pitch_count: 1_000,
  pitch_types: [
    { code: "FF", season_count: 600, usage_pct: 60 },
    { code: "SL", season_count: 100, usage_pct: 10 },
    { code: "CH", season_count: 99, usage_pct: 9.9 },
    { code: "CU", season_count: 0, usage_pct: 10 },
  ],
};

test("comparison shows only pitch types with at least 10% actual season usage", () => {
  assert.deepEqual(visiblePitchTypes(data, true).map(({ code }) => code), ["FF", "SL"]);
  assert.equal(meetsMinimumUsage({ code: "CU", season_count: 0, usage_pct: 10 }, data), false);
});

test("standalone viewer preserves its existing complete pitch list", () => {
  assert.equal(visiblePitchTypes(data, false).length, 4);
});
