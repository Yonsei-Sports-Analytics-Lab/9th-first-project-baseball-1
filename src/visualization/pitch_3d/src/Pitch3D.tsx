"use client";

import { Canvas, useThree } from "@react-three/fiber";
import { Line, OrbitControls, PerspectiveCamera, Text } from "@react-three/drei";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

import type {
  PitchTrajectory,
  PitchVisualizationData,
  TrajectoryPoint,
} from "./types";
import { representativeTrajectories } from "./representative.ts";
import { MIN_USAGE_PERCENT, visiblePitchTypes } from "./pitch-filter.ts";
import "./pitch-3d.css";

const PITCH_COLORS: Record<string, string> = {
  FF: "#ef476f",
  FA: "#ff72ae",
  SI: "#ff9f1c",
  FC: "#a78bfa",
  SL: "#f6e652",
  ST: "#e879f9",
  CU: "#38bdf8",
  KC: "#21d9ce",
  CH: "#34d399",
  FS: "#6594ff",
  SV: "#f18a65",
  KN: "#a3a3a3",
  UNK: "#ffffff",
};

type CameraView = "umpire" | "pitcher" | "batter" | "side" | "top";
type PitcherRole = "input" | "similar";
type PitcherSelection = "both" | PitcherRole;

export type Pitch3DProps = {
  data: PitchVisualizationData;
  comparisonData?: PitchVisualizationData;
  className?: string;
};

function StadiumElements() {
  const homePlateShape = useMemo(() => {
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.lineTo(0.71, 0.71);
    shape.lineTo(0.71, 1.42);
    shape.lineTo(-0.71, 1.42);
    shape.lineTo(-0.71, 0.71);
    shape.closePath();
    return shape;
  }, []);

  return (
    <group>
      <group position={[0, -0.09, 0]} rotation={[-Math.PI / 2, 0, Math.PI]}>
        <mesh>
          <shapeGeometry args={[homePlateShape]} />
          <meshBasicMaterial color="white" side={THREE.DoubleSide} />
        </mesh>
      </group>

      <group position={[0, -0.08, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        {[-3, 3].map((x) => (
          <lineSegments key={x} position={[x, 0, 0]}>
            <edgesGeometry args={[new THREE.PlaneGeometry(4, 6)]} />
            <lineBasicMaterial color="white" opacity={0.75} transparent />
          </lineSegments>
        ))}
      </group>

      <Line points={[[3, 0, 3], [70, 0, 70]]} color="white" lineWidth={2} />
      <Line points={[[-3, 0, 3], [-70, 0, 70]]} color="white" lineWidth={2} />

      <lineSegments position={[0, 2.5, 0]}>
        <edgesGeometry args={[new THREE.BoxGeometry(1.41, 1.8, 0.35)]} />
        <lineBasicMaterial color="white" opacity={0.6} transparent />
      </lineSegments>

      <group position={[0, -0.1, 60.5]}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[9, 64]} />
          <meshStandardMaterial color="#5d4037" roughness={1} />
        </mesh>
        <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[2, 0.5]} />
          <meshStandardMaterial color="white" />
        </mesh>
      </group>
      <gridHelper args={[200, 100, 0x1a472a, 0x0f2f1a]} position={[0, -0.2, 50]} />
    </group>
  );
}
function CameraController({ view, tunnel }: { view: CameraView; tunnel: boolean }) {
  const { camera } = useThree();

  useEffect(() => {
    if (tunnel) {
      camera.position.set(0, 3.5, -2);
      camera.lookAt(0, 5, 55);
      return;
    }
    const views: Record<CameraView, { position: THREE.Vector3; target: THREE.Vector3 }> = {
      umpire: {
        position: new THREE.Vector3(0, 5, -8),
        target: new THREE.Vector3(0, 2, 25),
      },
      pitcher: {
        position: new THREE.Vector3(0, 6, 65),
        target: new THREE.Vector3(0, 1, 0),
      },
      batter: {
        position: new THREE.Vector3(-3.5, 4, 2),
        target: new THREE.Vector3(0, 3, 40),
      },
      side: {
        position: new THREE.Vector3(-20, 5, 30),
        target: new THREE.Vector3(0, 3, 25),
      },
      top: {
        position: new THREE.Vector3(0, 50, 25),
        target: new THREE.Vector3(0, 0, 25),
      },
    };
    camera.position.copy(views[view].position);
    camera.lookAt(views[view].target);
  }, [camera, tunnel, view]);

  return null;
}

function toLinePoints(points: TrajectoryPoint[]): [number, number, number][] {
  return points.map((point) => [point.x, point.y, point.z]);
}

function TrajectoryLine({
  trajectory,
  tunnel,
  dimmed,
  onHover,
  comparisonRole,
  showAllSamples,
}: {
  trajectory: PitchTrajectory;
  tunnel: boolean;
  dimmed: boolean;
  onHover: (pitchType: string | null) => void;
  comparisonRole?: "input" | "similar";
  showAllSamples: boolean;
}) {
  const points = useMemo(() => toLinePoints(trajectory.points), [trajectory.points]);
  const splitIndex = Math.max(1, Math.floor(points.length / 2));
  const firstHalf = points.slice(0, splitIndex + 1);
  const secondHalf = points.slice(splitIndex);
  const endpoint = points.at(-1);
  const isSimilar = comparisonRole === "similar";
  const baseColor = PITCH_COLORS[trajectory.pitch_type] ?? "#ffffff";
  const color = isSimilar
    ? `#${new THREE.Color(baseColor).lerp(new THREE.Color("#ffffff"), 0.28).getHexString()}`
    : baseColor;

  if (points.length < 2 || !endpoint) return null;

  const eventHandlers = {
    onPointerOver: (event: { stopPropagation: () => void }) => {
      event.stopPropagation();
      onHover(trajectory.pitch_type);
    },
    onPointerOut: () => onHover(null),
  };

  return (
    <group>
      <Line
        points={firstHalf}
        color={tunnel ? "#b9c8c0" : color}
        dashed={isSimilar}
        dashSize={0.9}
        gapSize={0.5}
        lineWidth={dimmed ? 0.5 : showAllSamples ? 1.2 : isSimilar ? 2.9 : 2.2}
        opacity={dimmed ? 0.04 : tunnel ? 0.6 : showAllSamples ? 0.2 : 0.45}
        transparent
        {...eventHandlers}
      />
      <Line
        points={secondHalf}
        color={color}
        dashed={isSimilar}
        dashSize={0.9}
        gapSize={0.5}
        lineWidth={dimmed ? 0.5 : showAllSamples ? 1.6 : isSimilar ? 4.2 : 3}
        opacity={dimmed ? 0.04 : tunnel ? 0.7 : showAllSamples ? 0.35 : 0.9}
        transparent
        {...eventHandlers}
      />
      <mesh position={endpoint}>
        {isSimilar ? <octahedronGeometry args={[0.12, 0]} /> : <sphereGeometry args={[0.11, 12, 12]} />}
        <meshBasicMaterial color={color} opacity={dimmed ? 0.06 : 1} transparent />
      </mesh>
    </group>
  );
}

function Heatmap({ trajectories }: { trajectories: PitchTrajectory[] }) {
  const cells = useMemo(() => {
    const cellSize = 0.25;
    const counts = new Map<string, number>();
    for (const trajectory of trajectories) {
      const endpoint = trajectory.points.at(-1);
      if (!endpoint) continue;
      const xIndex = Math.floor((endpoint.x + 1.75) / cellSize);
      const yIndex = Math.floor((endpoint.y - 1) / cellSize);
      const key = `${xIndex},${yIndex}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const maximum = Math.max(0, ...counts.values());
    return [...counts.entries()].map(([key, count]) => {
      const [xIndex, yIndex] = key.split(",").map(Number);
      return {
        key,
        x: xIndex * cellSize - 1.75 + cellSize / 2,
        y: yIndex * cellSize + 1 + cellSize / 2,
        size: cellSize,
        intensity: maximum ? count / maximum : 0,
      };
    });
  }, [trajectories]);

  return (
    <group renderOrder={1}>
      {cells.map((cell) => (
        <mesh key={cell.key} position={[cell.x, cell.y, -0.03]}>
          <boxGeometry args={[cell.size * 0.95, cell.size * 0.95, 0.05]} />
          <meshBasicMaterial
            color="#ffffff"
            opacity={0.08 + cell.intensity * 0.38}
            transparent
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

export default function Pitch3D({ data, comparisonData, className = "" }: Pitch3DProps) {
  const [view, setView] = useState<CameraView>("umpire");
  const [pitcherSelection, setPitcherSelection] = useState<PitcherSelection>("both");
  const [activeTypes, setActiveTypes] = useState<Record<PitcherRole, string[]>>({ input: [], similar: [] });
  const [hoveredType, setHoveredType] = useState<string | null>(null);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showTunnel, setShowTunnel] = useState(false);
  const [showAllSamples, setShowAllSamples] = useState(false);

  const pitchGroups = useMemo(() => [
    { role: "input" as const, viewerData: data, pitchTypes: visiblePitchTypes(data, Boolean(comparisonData)) },
    ...(comparisonData ? [{ role: "similar" as const, viewerData: comparisonData, pitchTypes: visiblePitchTypes(comparisonData, true) }] : []),
  ], [data, comparisonData]);
  const selectedGroups = pitchGroups.filter(({ role }) => pitcherSelection === "both" || pitcherSelection === role);

  useEffect(() => {
    setPitcherSelection("both");
    setActiveTypes({
      input: pitchGroups[0].pitchTypes.map((pitchType) => pitchType.code),
      similar: pitchGroups[1]?.pitchTypes.map((pitchType) => pitchType.code) ?? [],
    });
    setShowAllSamples(false);
  }, [pitchGroups]);

  const sampledTrajectories = selectedGroups.flatMap(({ role, viewerData, pitchTypes }) => {
    const allowedTypes = new Set(pitchTypes.map((item) => item.code));
    return viewerData.trajectories
      .filter((item) => allowedTypes.has(item.pitch_type) && activeTypes[role].includes(item.pitch_type))
      .map((trajectory) => ({ trajectory, source: role }));
  });

  const visibleTrajectories = !comparisonData || showAllSamples ? sampledTrajectories : selectedGroups.flatMap(({ role, viewerData }) =>
    representativeTrajectories(
      sampledTrajectories.filter((item) => item.source === role).map((item) => item.trajectory),
      viewerData.pitch_types,
    )
      .map((trajectory) => ({ trajectory, source: role }))
  );

  const toggleType = (role: PitcherRole, pitchType: string) => {
    setActiveTypes((current) => ({
      ...current,
      [role]: current[role].includes(pitchType)
        ? current[role].filter((item) => item !== pitchType)
        : [...current[role], pitchType],
    }));
  };

  const allVisible = selectedGroups.some(({ pitchTypes }) => pitchTypes.length > 0) && selectedGroups.every(({ role, pitchTypes }) =>
    pitchTypes.every((pitchType) => activeTypes[role].includes(pitchType.code))
  );
  const toggleAllTypes = () => setActiveTypes((current) => {
    const next = { ...current };
    for (const { role, pitchTypes } of selectedGroups) {
      next[role] = allVisible ? [] : pitchTypes.map((pitchType) => pitchType.code);
    }
    return next;
  });

  return (
    <section className={`pitch3d ${className}`.trim()}>
      <div className="pitch3d__scene">
        <header className="pitch3d__header">
          <div>
            <p className="pitch3d__eyebrow">PITCH TRAJECTORY</p>
            <h2>{comparisonData ? `${data.pitcher.name} vs ${comparisonData.pitcher.name}` : data.pitcher.name}</h2>
          </div>
          <span>{comparisonData && !showAllSamples ? `대표 ${visibleTrajectories.length}구 / 표본 ${sampledTrajectories.length}구` : `${visibleTrajectories.length.toLocaleString()} pitches`}</span>
        </header>

        {comparisonData && <div className="pitch3d__legend"><span><i className="pitch3d__line pitch3d__line--input" />{data.pitcher.name}</span><span><i className="pitch3d__line pitch3d__line--similar" />{comparisonData.pitcher.name}</span></div>}

        <div className="pitch3d__toggles">
          {comparisonData && <button
            className={showAllSamples ? "is-active" : ""}
            aria-pressed={showAllSamples}
            onClick={() => setShowAllSamples((value) => !value)}
          >{showAllSamples ? "대표 궤적 보기" : "전체 표본 보기"}</button>}
          <button className={showHeatmap ? "is-active" : ""} onClick={() => setShowHeatmap((value) => !value)}>
            {showHeatmap ? "도착 밀도 끄기" : "도착 밀도 보기"}
          </button>
          <button className={showTunnel ? "is-active" : ""} aria-pressed={showTunnel} onClick={() => setShowTunnel((value) => !value)}>
            {showTunnel ? "터널 모드 끄기" : "터널 모드 켜기"}
          </button>
        </div>

        {!showTunnel && (
          <nav className="pitch3d__views" aria-label="카메라 시점">
            {(["umpire", "pitcher", "batter", "side", "top"] as CameraView[]).map((cameraView) => (
              <button
                key={cameraView}
                className={view === cameraView ? "is-active" : ""}
                onClick={() => setView(cameraView)}
              >
                {cameraView}
              </button>
            ))}
          </nav>
        )}

        <Canvas dpr={[1, 2]}>
          <PerspectiveCamera makeDefault fov={45} />
          <color attach="background" args={["#111714"]} />
          <fog attach="fog" args={["#111714", 35, 150]} />
          <ambientLight intensity={0.5} />
          <spotLight position={[10, 80, 20]} angle={0.5} penumbra={1} intensity={1.4} />
          <pointLight position={[-10, 10, 0]} intensity={0.7} color="#ccccff" />
          <StadiumElements />
          <CameraController view={view} tunnel={showTunnel} />
          <OrbitControls makeDefault target={showTunnel ? [0, 5, 55] : [0, 2, 25]} maxPolarAngle={Math.PI / 1.9} />
          {showHeatmap && <Heatmap trajectories={sampledTrajectories.map((item) => item.trajectory)} />}
          {visibleTrajectories.map(({ trajectory, source }) => (
            <TrajectoryLine
              key={`${source}:${trajectory.id}`}
              trajectory={trajectory}
              tunnel={showTunnel}
              dimmed={hoveredType !== null && hoveredType !== trajectory.pitch_type}
              onHover={setHoveredType}
              comparisonRole={comparisonData ? source as "input" | "similar" : undefined}
              showAllSamples={showAllSamples}
            />
          ))}
          {hoveredType && (
            <Text position={[0, 7.5, 4]} fontSize={0.7} color="white" anchorX="center">
              {selectedGroups.flatMap(({ pitchTypes }) => pitchTypes).find((item) => item.code === hoveredType)?.name ?? hoveredType}
            </Text>
          )}
        </Canvas>
      </div>

      <aside className="pitch3d__sidebar">
        {comparisonData && <div className="pitch3d__pitcher-filter">
          <span>투수 선택</span>
          <div className="pitch3d__pitcher-options" role="group" aria-label="비교할 투수 선택">
            {([
              ["both", "두 투수 비교"],
              ["input", data.pitcher.name],
              ["similar", comparisonData.pitcher.name],
            ] as const).map(([selection, label]) => (
              <button
                key={selection}
                type="button"
                className={pitcherSelection === selection ? "is-active" : ""}
                aria-pressed={pitcherSelection === selection}
                onClick={() => { setPitcherSelection(selection); setHoveredType(null); }}
              >{label}</button>
            ))}
          </div>
        </div>}
        <div className="pitch3d__filter-heading">
          <span>구종 필터 · 구사율 {MIN_USAGE_PERCENT}% 이상</span>
          <button type="button" onClick={toggleAllTypes}>
            {allVisible ? "모두 숨기기" : "모두 보기"}
          </button>
        </div>
        {comparisonData && <p className="pitch3d__selection-note">기본값은 시즌 전체 도착 위치의 최빈 0.25ft 구간에 가까운 실제 투구 1개입니다.</p>}
        {selectedGroups.map(({ role, viewerData, pitchTypes }) => <div className={`pitch3d__pitch-group pitch3d__pitch-group--${role}`} key={role}>
          {comparisonData && <h3>{viewerData.pitcher.name}</h3>}
          <div className="pitch3d__pitch-list">
          {[...pitchTypes].sort((left, right) =>
            (right.season_count ?? right.count) - (left.season_count ?? left.count)
          ).map((pitchType) => {
            const active = activeTypes[role].includes(pitchType.code);
            return (
              <button
                key={pitchType.code}
                type="button"
                className={active ? "is-active" : ""}
                aria-pressed={active}
                onClick={() => toggleType(role, pitchType.code)}
                onPointerEnter={() => setHoveredType(pitchType.code)}
                onPointerLeave={() => setHoveredType(null)}
              >
                <i style={{ backgroundColor: PITCH_COLORS[pitchType.code] ?? "#fff" }} />
                <span>
                  <strong>{pitchType.name} ({pitchType.code})</strong>
                  <small>
                    {(pitchType.season_count ?? pitchType.count).toLocaleString("ko-KR")}구 · {pitchType.average_speed_mph ?? "-"} mph · 구사율 {pitchType.usage_pct == null ? "—" : `${pitchType.usage_pct.toFixed(1)}%`}
                  </small>
                </span>
              </button>
            );
          })}
          {pitchTypes.length === 0 && <p className="pitch3d__selection-note">구사율 {MIN_USAGE_PERCENT}% 이상인 구종이 없습니다.</p>}
          </div>
        </div>)}
        {data.skipped.length > 0 && (
          <p className="pitch3d__notice">필수 값이 없는 {data.skipped.length}개 행은 제외되었습니다.</p>
        )}
      </aside>
    </section>
  );
}
