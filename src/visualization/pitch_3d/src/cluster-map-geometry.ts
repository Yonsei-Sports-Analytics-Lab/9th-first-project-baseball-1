import type { ClusterMapData } from "./types";

export type AxisBounds = [number, number];
/** Source dimensions: horizontal IVB, vertical arm-side HB. Arm angle remains part of the GMM only. */
export type MapBounds = [AxisBounds, AxisBounds];

export const PLOT = { left: 70, right: 884, top: 70, bottom: 416 } as const;

export function clusterMapBounds(data: ClusterMapData, focusCluster: number | null = null): MapBounds {
  const axes: number[][] = [[], []];
  const add = (point: readonly number[]) => { axes[0].push(point[0]); axes[1].push(point[1]); };
  data.points.filter((point) => focusCluster === null || point[3] === focusCluster).forEach(add);
  data.pitchers.forEach((pitcher) => add(pitcher.point));
  return axes.map((values) => {
    if (!values.length) throw new Error("표시할 GMM 군집 좌표가 없습니다.");
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const padding = Math.max((maximum - minimum) * 0.1, 1);
    return [minimum - padding, maximum + padding] as AxisBounds;
  }) as MapBounds;
}

/** A pitcher is one mean IVB-HB point. The third arm-angle value never changes its plot position. */
export function mapPoint(point: readonly number[], bounds: MapBounds): [number, number] {
  const x = PLOT.left + (point[0] - bounds[0][0]) / (bounds[0][1] - bounds[0][0]) * (PLOT.right - PLOT.left);
  const y = PLOT.bottom - (point[1] - bounds[1][0]) / (bounds[1][1] - bounds[1][0]) * (PLOT.bottom - PLOT.top);
  return [x, y];
}
