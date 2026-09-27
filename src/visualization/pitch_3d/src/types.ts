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
};

export type PitchVisualizationData = {
  schema_version: 1;
  pitcher: { name: string; id: string | null };
  source_files: string[];
  pitch_count: number;
  selected_row_count: number;
  pitch_types: PitchTypeSummary[];
  trajectories: PitchTrajectory[];
  skipped: Array<{
    source_file: string;
    source_row: string;
    reason: string;
  }>;
};
