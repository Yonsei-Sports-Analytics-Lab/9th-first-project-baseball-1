export type TrajectoryPoint = {
  x: number;
  y: number;
  z: number;
  time: number;
  speed_mph: number;
};

export type PitchTrajectory = {
  id: string;
  pitch_type: string;
  pitch_name: string;
  release_speed: number | null;
  method: "statcast" | "movement" | string;
  flight_time: number;
  points: TrajectoryPoint[];
};

export type PitchTypeSummary = {
  code: string;
  name: string;
  count: number;
  average_speed_mph: number | null;
  season_count?: number;
  usage_pct?: number;
  modal_plate_x?: number | null;
  modal_plate_z?: number | null;
  modal_plate_count?: number;
  modal_plate_grid_ft?: number;
};

export type PitchVisualizationData = {
  schema_version: 1;
  pitcher: { name: string; id: string | null };
  source_files: string[];
  pitch_count: number;
  selected_row_count: number;
  season_pitch_count?: number;
  trajectory_cache_version?: number;
  pitch_types: PitchTypeSummary[];
  trajectories: PitchTrajectory[];
  skipped: Array<{
    source_file: string;
    source_row: string;
    reason: string;
  }>;
};

export type ClusterMapData = {
  schema_version: number;
  k: number;
  total_pitches: number;
  sample_per_cluster: number;
  points: Array<[number, number, number, number]>;
  clusters: Array<{
    id: number;
    center: [number, number, number];
    shape_matrix: number[][];
    n_pitches: number;
  }>;
  pitchers: Array<{
    role: "input" | "similar";
    player_id: number;
    year: number;
    cluster: number;
    point: [number, number, number];
    n_pitches: number;
    total_fastballs: number;
    cluster_share_pct: number;
  }>;
};
