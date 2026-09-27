"use client";

import { useEffect, useState } from "react";

import { Pitch3D } from "../src";
import type { PitchVisualizationData } from "../src";

export default function BasicExample() {
  const [data, setData] = useState<PitchVisualizationData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/pitch-data.json")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<PitchVisualizationData>;
      })
      .then(setData)
      .catch((reason: unknown) => setError(String(reason)));
  }, []);

  if (error) return <p>투구 데이터를 불러오지 못했습니다: {error}</p>;
  if (!data) return <p>투구 데이터를 불러오는 중입니다.</p>;
  return <Pitch3D data={data} />;
}
