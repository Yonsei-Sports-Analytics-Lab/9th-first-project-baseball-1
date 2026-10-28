import type { PitchTrajectory, PitchTypeSummary } from "./types";

const MODE_BIN_FT = 0.25;

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function nearestTo(group: PitchTrajectory[], targetX: number, targetY: number): PitchTrajectory {
  return group.reduce((best, current) => {
    const distance = (pitch: PitchTrajectory) => {
      const end = pitch.points.at(-1)!;
      return (end.x - targetX) ** 2 + (end.y - targetY) ** 2;
    };
    return distance(current) < distance(best) ? current : best;
  });
}

/** Fallback for standalone/older payloads: the modal landing bin among available real samples. */
function sampledMode(group: PitchTrajectory[]): PitchTrajectory {
  const bins = new Map<string, { x: number; y: number; pitches: PitchTrajectory[] }>();
  for (const pitch of group) {
    const end = pitch.points.at(-1)!;
    const x = Math.floor(end.x / MODE_BIN_FT);
    const y = Math.floor(end.y / MODE_BIN_FT);
    const key = `${x}:${y}`;
    const bin = bins.get(key) ?? { x, y, pitches: [] };
    bin.pitches.push(pitch);
    bins.set(key, bin);
  }
  const medianX = median(group.map((pitch) => pitch.points.at(-1)!.x));
  const medianY = median(group.map((pitch) => pitch.points.at(-1)!.y));
  const ranked = [...bins.values()].sort((left, right) => {
    if (left.pitches.length !== right.pitches.length) return right.pitches.length - left.pitches.length;
    const distance = (bin: typeof left) => {
      const centerX = (bin.x + 0.5) * MODE_BIN_FT;
      const centerY = (bin.y + 0.5) * MODE_BIN_FT;
      return (centerX - medianX) ** 2 + (centerY - medianY) ** 2;
    };
    return distance(left) - distance(right) || left.x - right.x || left.y - right.y;
  });
  const bin = ranked[0];
  return nearestTo(bin.pitches, (bin.x + 0.5) * MODE_BIN_FT, (bin.y + 0.5) * MODE_BIN_FT);
}

/** One actual pitch nearest the full-season modal plate-location bin for each type. */
export function representativeTrajectories(
  trajectories: PitchTrajectory[],
  pitchTypes: Pick<PitchTypeSummary, "code" | "modal_plate_x" | "modal_plate_z">[] = [],
): PitchTrajectory[] {
  const groups = new Map<string, PitchTrajectory[]>();
  for (const trajectory of trajectories) {
    if (trajectory.points.length < 2) continue;
    const end = trajectory.points.at(-1)!;
    if (!Number.isFinite(end.x) || !Number.isFinite(end.y)) continue;
    const group = groups.get(trajectory.pitch_type) ?? [];
    group.push(trajectory);
    groups.set(trajectory.pitch_type, group);
  }

  return [...groups].map(([code, group]) => {
    const summary = pitchTypes.find((item) => item.code === code);
    if (summary?.modal_plate_x != null && summary.modal_plate_z != null) {
      // Statcast plate_x is negated in the Three.js scene; plate_z becomes scene Y.
      return nearestTo(group, -summary.modal_plate_x, summary.modal_plate_z);
    }
    return sampledMode(group);
  });
}
