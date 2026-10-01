import type { PitchTrajectory } from "./types";

/** One *observed* pitch per type, nearest the sampled group's median path. */
export function representativeTrajectories(trajectories: PitchTrajectory[]): PitchTrajectory[] {
  const groups = new Map<string, PitchTrajectory[]>();
  for (const trajectory of trajectories) {
    if (trajectory.points.length < 2) continue;
    const group = groups.get(trajectory.pitch_type) ?? [];
    group.push(trajectory);
    groups.set(trajectory.pitch_type, group);
  }

  return [...groups.values()].map((group) => {
    if (group.length === 1) return group[0];
    const features = group.map((trajectory) => {
      const points = trajectory.points;
      const start = points[0];
      const middle = points[Math.floor(points.length / 2)];
      const end = points[points.length - 1];
      return [start.x, start.y, middle.x, middle.y, end.x, end.y, trajectory.release_speed ?? start.speed_mph];
    });
    const median = features[0].map((_, index) => {
      const values = features.map((feature) => feature[index]).sort((left, right) => left - right);
      const midpoint = Math.floor(values.length / 2);
      return values.length % 2 ? values[midpoint] : (values[midpoint - 1] + values[midpoint]) / 2;
    });
    const scales = [2, 2, 2, 2, 2, 2, 5]; // feet for positions, mph for velocity
    let best = 0;
    let bestScore = Infinity;
    features.forEach((feature, index) => {
      const score = feature.reduce((sum, value, featureIndex) =>
        sum + ((value - median[featureIndex]) / scales[featureIndex]) ** 2, 0);
      if (score < bestScore) {
        best = index;
        bestScore = score;
      }
    });
    return group[best];
  });
}
