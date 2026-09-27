# Pitch 3D viewer

이 디렉터리는 `data/processed/data_*.csv`의 개별 Statcast 투구를 표시하는
React Three Fiber 컴포넌트입니다. 궤적 계산은 브라우저에서 반복하지 않고
상위 Python 모듈 `pitch_trajectory.py`의 결과만 렌더링합니다.

## 1. 데이터 생성

CSV가 한 투수만 포함하면 다음 명령으로 충분합니다.

```bash
python3 -m src.visualization.dashboard_formatter
```

여러 투수가 있으면 이름을 확인한 뒤 선택합니다.

```bash
python3 -m src.visualization.dashboard_formatter --list-pitchers
python3 -m src.visualization.dashboard_formatter --pitcher "Shohei Ohtani"
```

기본 입력은 `data/processed/data_*.csv`, 출력은 이 디렉터리의
`public/pitch-data.json`입니다. 렌더링 부담을 제한하기 위해 기본 300개를
시간 순서 전체에서 균등 추출합니다. 전부 내보내려면 충분히 큰 값을 지정합니다.

```bash
python3 -m src.visualization.dashboard_formatter --max-pitches 10000
```

필수 열은 운동 파라미터가 있는 개별 Statcast 행과 평균 데이터로 나뉩니다.

- 권장: `pitch_type`, `pitch_name`, `release_speed`, `plate_x`, `plate_z`,
  `release_pos_y`, `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az`
- 보조 모델: 위 운동 파라미터 대신 `release_pos_x`, `release_pos_z`,
  `release_pos_y`(또는 `release_extension`), `pfx_x`, `pfx_z`
- 투수 선택: `player_name`, `pitcher_name`, `pitcher_full_name`, `name` 중 하나

Baseball Savant CSV의 `pfx_x`, `pfx_z`는 feet로 취급합니다.

## 2. React에서 사용

```tsx
import { useEffect, useState } from "react";
import { Pitch3D, type PitchVisualizationData } from "./pitch_3d/src";

export function PitcherView() {
  const [data, setData] = useState<PitchVisualizationData | null>(null);
  useEffect(() => {
    fetch("/pitch-data.json").then((response) => response.json()).then(setData);
  }, []);
  return data ? <Pitch3D data={data} /> : null;
}
```

`public/pitch-data.json`을 실제 앱의 public 디렉터리로 복사하거나 빌드 과정에서
Python 변환기의 `--output`을 앱 public 경로로 지정하세요. 생성 JSON은 원본 CSV와
마찬가지로 Git에 올리지 않는 것을 권장합니다.
