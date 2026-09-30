# 3D 투구 궤적 통합 안내

> 상태: CSV 어댑터, Statcast 궤적 복원, React Three Fiber 뷰어 통합 완료

## 데이터 흐름

```text
data/processed/data_*.csv
        ↓
dashboard_formatter.py (파일 탐색·투수 선택·검증)
        ↓
pitch_trajectory.py (개별 투구 궤적 복원·Three.js 좌표 변환)
        ↓
pitch_3d/public/pitch-data.json
        ↓
Pitch3D.tsx (계산 없이 좌표 렌더링)
```

물리 계산은 Python 한 곳에서만 수행합니다. 프런트엔드는 mph 변환, `pfx` 단위
변환, 좌우 반전 또는 비행시간 계산을 하지 않습니다.

## 파일 위치

```text
src/visualization/
├── pitch_trajectory.py          Statcast·movement 궤적 복원
├── dashboard_formatter.py       data_*.csv → pitch-data.json
└── pitch_3d/
    ├── src/Pitch3D.tsx          3D 화면
    ├── src/types.ts             JSON 데이터 계약
    ├── src/pitch-3d.css         독립 스타일
    ├── examples/BasicExample.tsx
    ├── public/                   생성 JSON 위치
    ├── package.json
    └── README.md
```

## 입력 파일 규칙

`data/processed`에 `data_[설명].csv` 형태로 저장합니다. 변환기는 기본적으로
`data_*.csv`를 모두 읽습니다.

개별 Statcast 투구에 권장하는 열은 다음과 같습니다.

| 역할 | 열 |
|---|---|
| 투수 선택 | `player_name` 또는 `pitcher_name`; 선택적으로 `pitcher` ID |
| 구종 | `pitch_type`, `pitch_name` |
| 표시 정보 | `release_speed`, `game_year` |
| 위치 | `release_pos_x/y/z`, `plate_x`, `plate_z` |
| 운동 파라미터 | `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az` |

운동 파라미터가 없으면 `release_speed`, 릴리스 위치, 플레이트 위치,
`pfx_x`, `pfx_z`가 모두 있는 행에 한해 movement 보조 모델을 사용합니다.
Baseball Savant CSV의 `pfx_x/z`는 feet로 취급합니다.

## 실행

투수 목록을 확인합니다.

```bash
python3 -m src.visualization.dashboard_formatter --list-pitchers
```

CSV에 한 투수만 있으면 바로 생성할 수 있습니다.

```bash
python3 -m src.visualization.dashboard_formatter
```

여러 투수가 있으면 대소문자를 무시한 완전 일치 이름으로 선택합니다.

```bash
python3 -m src.visualization.dashboard_formatter --pitcher "Shohei Ohtani"
```

기본 출력은 `src/visualization/pitch_3d/public/pitch-data.json`입니다. 한 번에 너무
많은 Three.js 선을 만들지 않도록 전체 기간에서 최대 300개 행을 균등 추출합니다.
필요하면 `--max-pitches`와 `--samples`를 조정합니다.

```bash
python3 -m src.visualization.dashboard_formatter --pitcher "Shohei Ohtani" --max-pitches 500 --samples 41
```

특정 파일이나 다른 React 앱의 public 디렉터리도 지정할 수 있습니다.

```bash
python3 -m src.visualization.dashboard_formatter data/processed/data_ohtani_2024.csv \
  --output client/public/pitch-data.json
```

## 좌표와 결과 해석

Python 출력은 Three.js 좌표입니다.

```text
x = 화면 좌우 = -Statcast x
y = 화면 높이 = Statcast z
z = 화면 깊이 = Statcast y - plate_y
```

따라서 홈 플레이트 교차점의 깊이는 `z=0`입니다. `method=statcast`는 공개 운동
파라미터를 이용한 재구성이고, `method=movement`는 집계값 기반 대표 궤적입니다.
이는 영상 프레임의 실측 경로를 복원한다는 뜻은 아닙니다.

유효하지 않은 행은 payload의 `skipped`에 파일명, CSV 행 번호, 사유와 함께
기록됩니다. 유효한 행이 하나도 없으면 변환 명령이 실패합니다.

## 화면 기능

- CSV의 개별 투구를 구종 색상별로 동시에 렌더링
- 구종별 표시/숨김과 전체 토글
- umpire, pitcher, batter, side, top 카메라
- 플레이트 위치 히트맵
- 앞 절반을 중립색으로 표시하는 터널 보기
- 모바일에서 하단 구종 패널로 전환

기존 portable 코드의 브라우저 물리 공식, inch 고정 `pfx`, 결측 기본값,
Tailwind 결합은 제거했습니다.

## 검증

```bash
python3 -m unittest discover -s tests -v
cd src/visualization/pitch_3d
npm ci
npm exec -- tsc --noEmit
```

실제 데이터가 들어오면 추가로 확인할 항목은 좌·우투 좌우 방향, 구종별
`release_error_ft`, 비행시간 이상치, 제외 행 비율입니다. 대용량 CSV와 생성된
`pitch-data.json`은 Git에 커밋하지 않습니다.
