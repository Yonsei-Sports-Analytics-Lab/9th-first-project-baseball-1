import type { PitchTypeSummary, PitchVisualizationData } from "./types";

export const MIN_USAGE_PERCENT = 10;

/** Use unrounded season counts when available so 9.96% is not displayed as 10%. */
export function meetsMinimumUsage(pitchType: PitchTypeSummary, data: PitchVisualizationData): boolean {
  if (pitchType.season_count != null && data.season_pitch_count != null && data.season_pitch_count > 0) {
    return pitchType.season_count * 100 >= MIN_USAGE_PERCENT * data.season_pitch_count;
  }
  return pitchType.usage_pct != null && pitchType.usage_pct >= MIN_USAGE_PERCENT;
}

export function visiblePitchTypes(data: PitchVisualizationData, comparisonMode: boolean): PitchTypeSummary[] {
  return comparisonMode
    ? data.pitch_types.filter((pitchType) => meetsMinimumUsage(pitchType, data))
    : data.pitch_types;
}
