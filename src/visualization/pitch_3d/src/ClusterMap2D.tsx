"use client";

import { useEffect, useMemo, useState } from "react";

import { clusterMapBounds, ellipseBoundary, mapPoint, PLOT, type MapBounds } from "./cluster-map-geometry.ts";
import type { ClusterMapData } from "./types";
import "./cluster-map.css";

const COLORS = ["#57c7ff", "#ffa857", "#a5e075", "#d79aff", "#ff728a", "#f2db70", "#55ded0", "#b4bfff"];
const colorFor = (id: number) => COLORS[id % COLORS.length];
const format = (value: number, digits = 1) => value.toFixed(digits);

function ticks([minimum, maximum]: MapBounds[number]): number[] {
  return Array.from({ length: 5 }, (_, index) => minimum + (maximum - minimum) * index / 4);
}

function tickLabel(value: number, bounds: MapBounds[number]): string {
  return (bounds[1] - bounds[0] >= 25 ? value.toFixed(0) : value.toFixed(1));
}

function clusterPath(cluster: ClusterMapData["clusters"][number], bounds: MapBounds): string {
  return ellipseBoundary(cluster).map((point, index) => {
    const [x, y] = mapPoint(point, bounds);
    return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ") + " Z";
}

function ClusterPlot({ data, bounds, activeCluster, names }: {
  data: ClusterMapData;
  bounds: MapBounds;
  activeCluster: number | null;
  names: { input: string; similar: string };
}) {
  const clusters = data.clusters.filter((cluster) => activeCluster === null || cluster.id === activeCluster);
  const points = data.points.filter((point) => activeCluster === null || point[3] === activeCluster);
  const pitchers = data.pitchers;
  return <svg className="cluster-map__chart" viewBox="0 0 940 480" role="img"
    aria-label="가로축 IVB, 세로축 HB의 패스트볼 GMM 군집 분포와 두 투수의 평균 위치">
    <defs><clipPath id="cluster-map-clip"><rect x={PLOT.left} y={PLOT.top} width={PLOT.right - PLOT.left} height={PLOT.bottom - PLOT.top} /></clipPath></defs>
    <rect className="cluster-map__plot-bg" x={PLOT.left} y={PLOT.top} width={PLOT.right - PLOT.left} height={PLOT.bottom - PLOT.top} />
    {ticks(bounds[0]).map((tick, index) => {
      const [x] = mapPoint([tick, bounds[1][0]], bounds);
      return <g key={`ivb-${index}`}>
        <line className="cluster-map__grid-line" x1={x} x2={x} y1={PLOT.top} y2={PLOT.bottom} />
        <text className="cluster-map__tick" x={x} y={PLOT.bottom + 21} textAnchor="middle">{tickLabel(tick, bounds[0])}</text>
      </g>;
    })}
    {ticks(bounds[1]).map((tick, index) => {
      const [, y] = mapPoint([bounds[0][0], tick], bounds);
      return <g key={`hb-${index}`}>
        <line className="cluster-map__grid-line" x1={PLOT.left} x2={PLOT.right} y1={y} y2={y} />
        <text className="cluster-map__tick" x={PLOT.left - 10} y={y + 4} textAnchor="end">{tickLabel(tick, bounds[1])}</text>
      </g>;
    })}
    <text className="cluster-map__axis-label" x={(PLOT.left + PLOT.right) / 2} y="469" textAnchor="middle">보정 IVB (in)</text>
    <text className="cluster-map__axis-label" transform="translate(18 243) rotate(-90)" textAnchor="middle">암사이드 HB (in)</text>
    <g clipPath="url(#cluster-map-clip)">
      {clusters.map((cluster) => <path key={`area-${cluster.id}`} d={clusterPath(cluster, bounds)}
        className="cluster-map__region" fill={colorFor(cluster.id)} stroke={colorFor(cluster.id)} />)}
      {points.map((point, index) => {
        const [x, y] = mapPoint(point, bounds);
        return <circle key={`sample-${index}`} cx={x} cy={y} r="1.8" fill={colorFor(point[3])} className="cluster-map__sample" />;
      })}
    </g>
    {clusters.map((cluster) => {
      const [x, y] = mapPoint(cluster.center, bounds);
      return <text key={`label-${cluster.id}`} className="cluster-map__cluster-label" x={x} y={y - 8}
        textAnchor="middle" fill={colorFor(cluster.id)}>C{cluster.id}</text>;
    })}
    {pitchers.map((pitcher) => {
      const [x, y] = mapPoint(pitcher.point, bounds);
      const input = pitcher.role === "input";
      const toRight = !input && x < PLOT.right - 150;
      const labelX = x + (toRight ? 14 : -14);
      const labelY = y + (input ? -17 : 22);
      const color = "#ffffff";
      return <g key={pitcher.role} className="cluster-map__pitcher-point">
        <title>{names[pitcher.role]}</title>
        <line x1={x} y1={y} x2={labelX} y2={labelY} stroke={color} strokeOpacity="0.8" />
        <circle cx={x} cy={y} r="8" fill={input ? "#ffffff" : "#101923"}
          stroke={input ? "#101923" : "#ffffff"} strokeWidth={input ? "2" : "3"} />
        <text x={labelX} y={labelY} textAnchor={toRight ? "start" : "end"} fill={color}>
          {names[pitcher.role]}
        </text>
      </g>;
    })}
  </svg>;
}

export default function ClusterMap2D({ data, names }: { data: ClusterMapData; names: { input: string; similar: string } }) {
  const [activeCluster, setActiveCluster] = useState<number | null>(null);
  useEffect(() => setActiveCluster(null), [data]);
  const bounds = useMemo(() => clusterMapBounds(data, activeCluster), [data, activeCluster]);
  return <section className="cluster-map" aria-label="전체 패스트볼 GMM IVB-HB 2차원 분포">
    <div className="cluster-map__scene">
      <div className="cluster-map__scene-title"><strong>{activeCluster === null ? "전체 패스트볼 GMM · IVB × HB" : `군집 C${activeCluster} · IVB × HB`}</strong><span>군집 버튼으로 분포 선택 · 두 투수 평균점은 항상 표시</span></div>
      <ClusterPlot data={data} bounds={bounds} activeCluster={activeCluster} names={names} />
    </div>
    <div className="cluster-map__panel">
      <p className="cluster-map__panel-label">군집 영역 · 전체 패스트볼 {data.total_pitches.toLocaleString("ko-KR")}구</p>
      <div className="cluster-map__cluster-list" role="group" aria-label="GMM 군집 선택">
        <button type="button" className={activeCluster === null ? "is-active" : ""} aria-pressed={activeCluster === null} onClick={() => setActiveCluster(null)}>전체 보기</button>
        {data.clusters.map((cluster) => <button type="button" key={cluster.id}
          className={activeCluster === cluster.id ? "is-active" : ""} aria-pressed={activeCluster === cluster.id}
          onClick={() => setActiveCluster(activeCluster === cluster.id ? null : cluster.id)}>
          <i style={{ backgroundColor: colorFor(cluster.id) }} /> C{cluster.id}
          <small>{(cluster.n_pitches / data.total_pitches * 100).toFixed(1)}%</small>
        </button>)}
      </div>
      <div className="cluster-map__pitchers">
        {data.pitchers.map((pitcher) => <div key={pitcher.role} className="cluster-map__pitcher">
          <span className={`cluster-map__marker cluster-map__marker--${pitcher.role}`}>{pitcher.role === "input" ? "A" : "B"}</span>
          <div><strong>{names[pitcher.role]}</strong><small>{pitcher.year} · 최빈 군집 C{pitcher.cluster} ({format(pitcher.cluster_share_pct)}%)</small>
            <small>평균 IVB {format(pitcher.point[0])} · HB {format(pitcher.point[1])} in</small>
            <small className="cluster-map__angle">평균 팔 각도 {format(pitcher.point[2])}°</small></div>
        </div>)}
      </div>
      <p className="cluster-map__footnote">기존 GMM은 IVB·HB·팔 각도 3변수로 분류합니다. 차트는 IVB–HB 2차원 투영이며, 타원은 각 군집의 1.5σ 밀도 영역입니다. A·B는 각 시즌 FF·SI·FC 전체 평균을 나타내는 점 하나씩입니다. 여러 구종을 섞어 던지면 평균점이 최빈 군집 타원 밖에 있을 수 있습니다. 작은 점은 군집별 최대 {data.sample_per_cluster}개의 실제 투구 표본입니다.</p>
    </div>
  </section>;
}
