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
import "./pitch-3d.css";

const PITCH_COLORS: Record<string, string> = {
  FF: "#ef476f",
  FA: "#ef476f",
  SI: "#ff9f1c",
  FC: "#b86f52",
  SL: "#f6e652",
  ST: "#d9ed92",
  CU: "#38bdf8",
  KC: "#22d3ee",
  CH: "#34d399",
  FS: "#6387db",
  SV: "#e879f9",
  KN: "#a3a3a3",
  UNK: "#ffffff",
};

type CameraView = "umpire" | "pitcher" | "batter" | "side" | "top";

export type Pitch3DProps = {
  data: PitchVisualizationData;
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
}: {
  trajectory: PitchTrajectory;
  tunnel: boolean;
  dimmed: boolean;
  onHover: (pitchType: string | null) => void;
}) {
  const points = useMemo(() => toLinePoints(trajectory.points), [trajectory.points]);
  const splitIndex = Math.max(1, Math.floor(points.length / 2));
  const firstHalf = points.slice(0, splitIndex + 1);
  const secondHalf = points.slice(splitIndex);
  const endpoint = points.at(-1);
  const color = PITCH_COLORS[trajectory.pitch_type] ?? "#ffffff";

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
        color={tunnel ? "#cbd5e1" : color}
        lineWidth={dimmed ? 0.5 : 1.2}
        opacity={dimmed ? 0.04 : tunnel ? 0.12 : 0.2}
        transparent
        {...eventHandlers}
      />
      <Line
        points={secondHalf}
        color={color}
        lineWidth={dimmed ? 0.5 : 1.5}
        opacity={dimmed ? 0.04 : tunnel ? 0.65 : 0.32}
        transparent
        {...eventHandlers}
      />
      <mesh position={endpoint}>
        <sphereGeometry args={[0.055, 8, 8]} />
        <meshBasicMaterial color={color} opacity={dimmed ? 0.06 : 0.5} transparent />
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
            color={new THREE.Color().setHSL(0.62 - cell.intensity * 0.62, 1, 0.5)}
            opacity={0.2 + cell.intensity * 0.7}
            transparent
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

export default function Pitch3D({ data, className = "" }: Pitch3DProps) {
  const [view, setView] = useState<CameraView>("umpire");
  const [activeTypes, setActiveTypes] = useState<string[]>([]);
  const [hoveredType, setHoveredType] = useState<string | null>(null);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showTunnel, setShowTunnel] = useState(false);

  useEffect(() => {
    setActiveTypes(data.pitch_types.map((pitchType) => pitchType.code));
  }, [data]);

  const visibleTrajectories = useMemo(
    () => data.trajectories.filter((item) => activeTypes.includes(item.pitch_type)),
    [activeTypes, data.trajectories],
  );

  const toggleType = (pitchType: string) => {
    setActiveTypes((current) =>
      current.includes(pitchType)
        ? current.filter((item) => item !== pitchType)
        : [...current, pitchType],
    );
  };

  const allVisible = activeTypes.length === data.pitch_types.length;

  return (
    <section className={`pitch3d ${className}`.trim()}>
      <div className="pitch3d__scene">
        <header className="pitch3d__header">
          <div>
            <p className="pitch3d__eyebrow">PITCH TRAJECTORY</p>
            <h2>{data.pitcher.name}</h2>
          </div>
          <span>{visibleTrajectories.length.toLocaleString()} pitches</span>
        </header>

        <div className="pitch3d__toggles">
          <button className={showHeatmap ? "is-active" : ""} onClick={() => setShowHeatmap((value) => !value)}>
            {showHeatmap ? "히트맵 끄기" : "히트맵 켜기"}
          </button>
          <button className={showTunnel ? "is-active" : ""} onClick={() => setShowTunnel((value) => !value)}>
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
          <OrbitControls makeDefault target={[0, 2, 25]} maxPolarAngle={Math.PI / 1.9} />
          {showHeatmap && <Heatmap trajectories={visibleTrajectories} />}
          {visibleTrajectories.map((trajectory) => (
            <TrajectoryLine
              key={trajectory.id}
              trajectory={trajectory}
              tunnel={showTunnel}
              dimmed={hoveredType !== null && hoveredType !== trajectory.pitch_type}
              onHover={setHoveredType}
            />
          ))}
          {hoveredType && (
            <Text position={[0, 7.5, 4]} fontSize={0.7} color="white" anchorX="center">
              {data.pitch_types.find((item) => item.code === hoveredType)?.name ?? hoveredType}
            </Text>
          )}
        </Canvas>
      </div>

      <aside className="pitch3d__sidebar">
        <div className="pitch3d__filter-heading">
          <span>구종 필터</span>
          <button
            onClick={() =>
              setActiveTypes(allVisible ? [] : data.pitch_types.map((item) => item.code))
            }
          >
            {allVisible ? "모두 숨기기" : "모두 보기"}
          </button>
        </div>
        <div className="pitch3d__pitch-list">
          {data.pitch_types.map((pitchType) => {
            const active = activeTypes.includes(pitchType.code);
            return (
              <button
                key={pitchType.code}
                className={active ? "is-active" : ""}
                onClick={() => toggleType(pitchType.code)}
                onPointerEnter={() => setHoveredType(pitchType.code)}
                onPointerLeave={() => setHoveredType(null)}
              >
                <i style={{ backgroundColor: PITCH_COLORS[pitchType.code] ?? "#fff" }} />
                <span>
                  <strong>{pitchType.name}</strong>
                  <small>
                    {pitchType.count}개 · {pitchType.average_speed_mph ?? "-"} mph
                  </small>
                </span>
              </button>
            );
          })}
        </div>
        {data.skipped.length > 0 && (
          <p className="pitch3d__notice">필수 값이 없는 {data.skipped.length}개 행은 제외되었습니다.</p>
        )}
      </aside>
    </section>
  );
}
