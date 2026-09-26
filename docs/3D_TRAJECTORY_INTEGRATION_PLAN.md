# 3D 투구 궤적 기능 결합 계획서

> 문서 목적: 다른 프로젝트의 3D 투구 시각화 기능을 이 저장소의 구조와 데이터 규칙에 맞게 결합한다.
> 대상 독자: 데이터 분석가, Python 개발자, 프런트엔드 개발자, 기획자
> 기준일: 2026-09-26
> 상태: 궤적 계산 모듈과 기본 단위 테스트 완료, 화면·API는 미구현

---

## 1. 한 페이지 요약

이 저장소에는 아직 React 화면이나 FastAPI 서버가 없다. 따라서 다른 프로젝트의
`Pitch3D.tsx`, `physics.py`, API 코드를 한꺼번에 복사하면 현재 구조와 맞지 않고,
같은 투구를 프런트엔드와 Python이 서로 다른 공식으로 계산하는 문제가 생긴다.

이 프로젝트의 권장 결합 방식은 다음과 같다.

```text
Statcast 원본 행
    ↓
Python 궤적 복원 모듈 (현재 구현 완료)
    ↓
JSON으로 직렬화할 수 있는 궤적 점
    ↓
향후 API 또는 작은 JSON fixture
    ↓
React/Three.js 화면은 받은 점만 렌더링
```

핵심 원칙은 세 가지다.

1. **궤적 계산은 Python 한 곳에서 관리한다.**
2. **원본 Statcast 단위와 좌표계를 중간에 임의로 바꾸지 않는다.**
3. **3D 화면은 물리 계산이 아니라 표현만 담당한다.**

현재 구현된 기준 모듈은
`src/visualization/pitch_trajectory.py`이다. 이 모듈은 Baseball Savant CSV의
운동 파라미터를 우선 사용하고, 값이 없을 때만 구속·무브먼트 기반 보조 모델을
사용한다.

---

## 2. 현재 저장소에서 이미 된 것과 아직 안 된 것

### 2.1 완료된 항목

| 항목 | 위치 | 설명 |
|---|---|---|
| Statcast 변수 설명 | `STATCAST_2021_03_변수설명서.md` | 단위, 결측 수, 해석 주의사항 정리 |
| 궤적 복원 함수 | `src/visualization/pitch_trajectory.py` | 실제 투구와 집계 데이터 모두 지원 |
| Three.js 좌표 변환 | 같은 파일 | `(-x, z, y - plate_y)` 변환 제공 |
| 입력 검증 | 같은 파일 | 결측, NaN, 무한대, 잘못된 속도·방향 검사 |
| 자동 테스트 | `tests/test_pitch_trajectory.py` | 종점, 축 변환, fallback, 단위 처리 검사 |

### 2.2 아직 없는 항목

| 항목 | 현재 상태 | 이번 결합에서의 처리 |
|---|---|---|
| 웹 API | 없음 | 데이터 전달 방식 결정 후 추가 |
| React/Next.js 프로젝트 | 없음 | 프런트엔드 기술 결정 후 `client/` 생성 |
| 3D 경기장·카메라 UI | 없음 | 참고 `Pitch3D.tsx`에서 표현 코드만 이관 |
| 실제 프로젝트 데이터 파일 | 저장소에 없음 | 원본은 `data/raw/`, 결과는 `data/processed/` 규칙 준수 |
| 대량 궤적 집계 | 없음 | 개별 복원 후 구종별 요약 로직 추가 필요 |

다른 프로젝트에 있던 다음 기능은 이번 3D 결합 범위가 아니다.

- LSTM 다음 구종 예측
- Run Value 계산
- 임시 난수 기반 결과 시뮬레이션
- Redis와 캐시 서버
- 투수 검색 화면 전체

이 기능들은 3D 궤적과 독립된 별도 이슈로 다룬다.

---

## 3. 왜 원 계획을 그대로 적용하지 않는가

원 계획은 완성된 Next.js/FastAPI 애플리케이션에서 3D 컴포넌트를 다른
프런트엔드로 옮기는 상황을 가정한다. 현재 프로젝트는 분석용 Python 저장소이므로
출발점이 다르다.

| 원 프로젝트의 전제 | 현재 프로젝트의 실제 상태 | 조정 방향 |
|---|---|---|
| Next.js가 이미 있음 | 프런트엔드 없음 | 먼저 데이터 계약을 고정한 뒤 화면 생성 |
| FastAPI가 이미 있음 | API 없음 | 초기에는 Python 결과와 fixture로 검증 |
| 프런트에서 궤적 계산 | Python 기준 모듈 구현 완료 | 프런트 재계산 제거 |
| API의 `pfx_*`가 inch | 현재 Statcast 원본은 ft | 기본 단위를 ft로 유지 |
| 평균 구종 궤적만 표현 | 개별 Statcast 운동 파라미터 사용 가능 | 실제 투구 복원을 우선 사용 |
| `physics.py` 항력 시뮬레이션 병존 | 아직 별도 엔진 불필요 | 기준 엔진을 하나로 유지 |

따라서 `Pitch3D.tsx` 전체 복사보다 “렌더링에 필요한 부분만 나중에 이관”하는
방법이 안전하다.

---

## 4. 팀원이 알아야 할 궤적 복원 원리

### 4.1 가장 정확한 경로: Statcast 운동 파라미터

개별 투구에 아래 값이 모두 있으면 `statcast` 방법을 사용한다.

```text
vx0, vy0, vz0  : y=50ft 지점의 x/y/z 속도 (ft/s)
ax, ay, az     : x/y/z 평균 가속도 (ft/s²)
plate_x/z      : 공이 홈 플레이트를 지날 때 위치 (ft)
release_pos_y  : 릴리스 지점과 홈 사이 거리 (ft)
```

각 축의 위치는 다음 식으로 구한다.

```text
position(t) = position(0) + velocity(0) × t + 1/2 × acceleration × t²
```

CSV에는 y=50ft에서의 x/z 위치가 없으므로 `plate_x`, `plate_z`에서 역산한다.
이 방식은 참고 `physics.py`처럼 임의의 홈 중앙을 목표로 정하지 않고, 실제로
기록된 플레이트 통과 위치를 보존한다.

### 4.2 보조 경로: 구종 평균값

구종별 평균 데이터처럼 6개 운동 파라미터가 없으면 다음 값으로 대표 궤적을
만든다.

```text
release_speed
release_pos_x, release_pos_z
release_pos_y 또는 release_extension
plate_x, plate_z
pfx_x, pfx_z
```

이 경로는 시작점과 도착점을 맞추고 `pfx`로 곡률을 근사한다. 실제 프레임별
추적을 되살리는 것이 아니라 **구종의 대표적인 모양을 보여 주는 보조 모델**이다.

### 4.3 사용자에게 표시할 문구

- 개별 투구 운동 파라미터 사용: `Statcast 기반 재구성 궤적`
- 구종 평균값 사용: `구종 평균 기반 대표 궤적`
- 피해야 할 표현: `실제 영상 복원`, `완전한 실측 비행 경로`

---

## 5. 데이터 단위와 좌표계

### 5.1 입력 단위

| 필드 | 단위 | 주의사항 |
|---|---:|---|
| `release_speed` | mph | ft/s가 아님 |
| `release_pos_x/y/z` | ft | 포수 시점 Statcast 좌표 |
| `release_extension` | ft | `release_pos_y`가 없을 때 거리 계산에 사용 |
| `plate_x`, `plate_z` | ft | 2025년까지 앞면, 2026년부터 중앙 기준 |
| `pfx_x`, `pfx_z` | ft | 이 저장소에서는 inch로 바꾸지 않고 사용 |
| `vx0`, `vy0`, `vz0` | ft/s | y=50ft 기준 |
| `ax`, `ay`, `az` | ft/s² | y=50ft 기준 평균 가속도 |

다른 프로젝트의 API가 `pfx`를 inch로 변환했다는 이유로 현재 데이터에도 `/12`를
적용하면 궤적이 거의 직선으로 잘못 표시된다. inch 입력을 정말 사용해야 할 때만
함수의 `pfx_unit="inches"` 옵션을 명시한다.

### 5.2 출력 좌표

`coordinate_system="statcast"`:

```text
x = 포수 시점 좌우
y = 홈에서 마운드 방향 거리
z = 지면으로부터 높이
```

`coordinate_system="threejs"`:

```text
x = 화면 좌우     = -Statcast x
y = 화면 높이     = Statcast z
z = 화면 깊이     = Statcast y - plate_y
```

Three.js 출력에서는 홈 플레이트가 깊이 `z=0`이다. 좌우 반전과 축 교환은 이미
Python 모듈이 수행하므로 프런트엔드에서 다시 반전하지 않는다.

---

## 6. 현재 Python API 사용법

### 6.1 한 투구 복원

```python
from src.visualization.pitch_trajectory import reconstruct_pitch_trajectory

result = reconstruct_pitch_trajectory(
    statcast_row,                 # dict 또는 pandas Series
    samples=61,
    method="auto",
    coordinate_system="threejs",
)

points = result["points"]
```

### 6.2 반환 형태

```json
{
  "method": "statcast",
  "coordinate_system": "threejs",
  "flight_time": 0.4012,
  "plate_y": 1.4167,
  "release_error_ft": {"x": 0.01, "z": -0.02},
  "points": [
    {"x": 1.82, "y": 5.94, "z": 53.02, "time": 0.0, "speed_mph": 96.1},
    {"x": -0.10, "y": 2.70, "z": 0.0, "time": 0.4012, "speed_mph": 87.9}
  ]
}
```

`release_error_ft`는 보고된 릴리스 위치와 운동식이 예측한 위치의 차이다. 데이터
품질 진단용이며 화면 좌표가 아니라 Statcast x/z 기준이다. 값이 지나치게 크면
해당 행의 측정값과 단위를 먼저 확인한다.

### 6.3 여러 투구 복원

```python
from src.visualization.pitch_trajectory import reconstruct_many

results = reconstruct_many(
    rows,
    samples=61,
    coordinate_system="threejs",
)
```

대량 CSV 전체를 한 번에 JSON으로 저장하지 않는다. 분석 목적에 맞게 투수·기간·
구종을 먼저 필터링하고 필요한 결과만 만든다.

---

## 7. 현재 프로젝트에 맞는 목표 구조

지금 바로 필요한 Python 구조는 단순하게 유지한다.

```text
src/
├── collection/                  Statcast 원본 수집
├── preprocessing/               결측 처리와 분석용 데이터 정리
├── visualization/
│   ├── pitch_trajectory.py       궤적 복원 기준 모듈 (완료)
│   └── dashboard_formatter.py    화면 전달용 구종 요약 JSON (추가 예정)
└── utils/                        공통 설정·로깅

tests/
├── fixtures/                     작고 익명화된 테스트 행만 저장
└── test_pitch_trajectory.py      계산 테스트 (완료)

docs/
└── 3D_TRAJECTORY_INTEGRATION_PLAN.md
```

웹 화면을 실제로 만들기로 결정한 뒤에만 다음 구조를 추가한다.

```text
client/src/features/pitch-trajectory/
├── types.ts
├── api.ts
├── PitchTrajectoryViewer.tsx
├── scene/
│   ├── StadiumElements.tsx
│   ├── TrajectoryTube.tsx
│   ├── PlateHeatmap.tsx
│   └── CameraController.tsx
└── controls/
    ├── PitchFilter.tsx
    └── CameraSelector.tsx
```

프런트엔드 기술이 정해지기 전에 `client/`나 `package.json`을 미리 만들지 않는다.

---

## 8. 프런트엔드 데이터 계약

프런트엔드는 원본 Statcast 필드나 운동 공식을 몰라도 된다. 다음 두 타입만 받는
것을 권장한다.

```ts
export interface TrajectoryPoint {
  x: number;        // 좌우, ft
  y: number;        // 높이, ft
  z: number;        // 홈에서의 깊이, ft; 홈은 0
  time: number;     // 릴리스 후 초
  speed_mph: number;
}

export interface PitchTrajectory {
  pitch_type: string;
  label: string;
  reconstruction_method: "statcast" | "movement";
  coordinate_system: "threejs";
  points: TrajectoryPoint[];
}
```

프런트엔드가 받아서는 안 되는 책임:

- mph를 ft/s로 바꾸기
- `pfx`의 ft/inch 변환
- x축 부호 반전
- 비행시간 계산
- 중력 또는 가속도 계산
- 결측치를 90mph 같은 임의값으로 대체

화면은 `points`를 `THREE.Vector3`로 바꾸고 선이나 튜브로 그리기만 한다.

---

## 9. 개별 투구와 구종 대표 궤적 정책

### 9.1 개별 투구 보기

운동 파라미터가 있는 각 행을 그대로 복원한다. 정확도가 가장 높지만 많은 공을
동시에 그리면 화면이 복잡하고 느려질 수 있다.

권장 용도:

- 최근 10~30구 재생
- 특정 타석 분석
- 투구 터널 비교

### 9.2 구종 대표 궤적 보기

여러 행의 모든 숫자를 먼저 평균내는 것보다 다음 순서가 안전하다.

```text
1. 개별 투구를 각각 61개 점으로 복원
2. 각 점의 진행률(0~100%)을 맞춤
3. 구종별로 같은 진행률의 x/y/z 중앙값 계산
4. 대표선과 25~75% 분산 영역 생성
```

이 방식은 릴리스 위치와 무브먼트, 종점 사이의 관계를 평균 과정에서 덜 잃는다.
운동 파라미터가 없는 집계 자료에만 `movement` 보조 모델을 사용한다.

권장 용도:

- 투수의 구종 arsenal 비교
- 한 화면에 여러 구종 표시
- 구종별 평균 터널 분석

---

## 10. 단계별 구현 계획

### 단계 0. 계산 기준 고정 — 완료

- [x] `src/visualization/pitch_trajectory.py` 생성
- [x] Statcast 6개 운동 파라미터 우선 사용
- [x] 집계 데이터 fallback 구현
- [x] Three.js 좌표 변환 구현
- [x] 기본 단위 테스트 작성

완료 기준: 현재 `python3 -m unittest discover -s tests -v`가 통과한다.

### 단계 1. 실제 데이터로 검증 — 다음 작업

1. 팀 공유 데이터에서 우투·좌투 각 1명, 주요 구종 2개 이상을 선택한다.
2. 운동 파라미터 결측률과 `release_error_ft` 분포를 확인한다.
3. 알려진 `plate_x`, `plate_z`와 궤적 종점이 일치하는지 확인한다.
4. 포수 시점에서 구종의 좌우 움직임이 반대로 보이지 않는지 검토한다.
5. 테스트용으로 5~10개 행만 익명화해 `tests/fixtures/`에 보관한다.

완료 기준:

- 최소 4개 구종이 실제 데이터로 검증된다.
- 좌우 방향과 단위가 데이터 담당자와 합의된다.
- 대용량 CSV는 Git에 추가되지 않는다.

### 단계 2. 구종 대표 궤적과 JSON formatter 구현

`src/visualization/dashboard_formatter.py`에 다음 기능을 둔다.

- 투수·기간·구종 필터링
- 개별 투구 궤적 생성
- 진행률별 중앙값 대표선 계산
- 구종명, 색상, 표본 수와 함께 JSON 변환
- 결측 행 개수와 제외 사유 기록

완료 기준:

- 동일 입력은 동일 JSON을 만든다.
- 출력에 모델 방법, 단위, 좌표계, 표본 수가 포함된다.
- 데이터가 없을 때 빈 결과와 이유를 명확히 반환한다.

### 단계 3. 데이터 전달 방식 결정

권장 기본안은 개발 초기에는 작은 fixture JSON, 실제 서비스 단계에는 API이다.

| 상황 | 권장 방식 |
|---|---|
| 분석 검증·UI 프로토타입 | 고정 fixture JSON |
| 사용자 검색과 기간 변경 필요 | Python API |
| 정적 리포트만 필요 | 사전 생성 JSON |
| 여러 클라이언트가 사용 | 버전이 있는 API |

API가 필요하다고 결정하면 그때 프레임워크를 선택하고 다음과 같은 경계를 둔다.

```http
GET /api/v1/pitchers/{pitcher_id}/trajectories?start=YYYY-MM-DD&end=YYYY-MM-DD
```

응답에는 `model_version`, `coordinate_system`, `pfx_unit`, `sample_count`를 포함한다.
API 서버는 `reconstruct_pitch_trajectory()`를 호출할 뿐 별도 수식을 만들지 않는다.

### 단계 4. 3D viewer 최소 기능 이관

참고 `Pitch3D.tsx`에서 다음만 먼저 옮긴다.

1. Canvas와 카메라
2. 홈 플레이트와 스트라이크 존
3. 전달받은 점을 그리는 `TrajectoryTube`
4. 구종 범례와 표시/숨김

처음부터 옮기지 않을 항목:

- 브라우저 안의 궤적 수식
- `any` 타입
- 데이터 누락 시 임의 기본값
- 히트맵, 터널 색상, 복잡한 경기장 장식
- 원 프로젝트의 API 호출 코드

완료 기준:

- 첫 점과 마지막 점이 Python 결과와 일치한다.
- 프런트엔드 코드에 `pfx`, `vx0`, `ax` 계산이 없다.
- 빈 데이터와 WebGL 미지원 안내가 있다.

### 단계 5. 선택 기능 추가

최소 viewer가 안정된 뒤 순서대로 추가한다.

1. 카메라 프리셋: umpire, pitcher, side, top
2. 구종 hover와 상세 정보
3. 최근 개별 투구 표시
4. 터널 모드
5. 플레이트 위치 히트맵
6. 모바일 레이아웃과 접근성 개선

각 기능은 별도 PR로 구현한다. 히트맵은 궤적 계산과 분리하고 `plate_x/z`만 사용한다.

### 단계 6. 운영 검증

- 브라우저별 시각 확인
- 모바일 성능과 DPR 제한 확인
- API timeout·오류·빈 데이터 처리
- Canvas가 화면 밖일 때 렌더 중지 검토
- 키보드 조작과 텍스트 표 제공
- 알고리즘 버전 변경 시 fixture 회귀 테스트

---

## 11. 참고 코드에서 가져올 것과 가져오지 않을 것

### 가져올 수 있는 것

- 홈 플레이트, 스트라이크 존, 마운드의 Three.js 표현
- 카메라 위치 프리셋
- OrbitControls 구성
- 구종별 색상·이름 체계
- 선 강조, hover label, 표시 필터 UX
- 터널 모드의 시각적 아이디어

### 그대로 가져오지 않을 것

- `SplitTrajectory` 내부의 궤적 계산식
- `physics.py`의 임의 목표점과 고정 drag factor
- `pfx`를 항상 inch로 가정하는 코드
- `release_pos_*`가 없을 때 조용히 넣는 기본값
- 조건부로 Hook을 호출하는 구조
- Tailwind와 Lucide를 필수로 만드는 UI 결합
- 원 프로젝트의 검색·예측·시뮬레이션 API

참고 코드는 화면 구성의 예시이며, 현재 프로젝트의 데이터 규칙보다 우선하지 않는다.

---

## 12. 테스트 계획

### 12.1 Python 단위 테스트

- 반환 점 개수
- 릴리스에서 플레이트까지 y가 계속 감소하는지
- 마지막 점이 `plate_x/z`와 일치하는지
- mph ↔ ft/s 변환
- ft와 inch `pfx` 옵션 차이
- 2025 앞면과 2026 중앙 기준 차이
- `release_pos_y`가 없을 때 extension 사용
- null, NaN, Infinity, 음수 구속 거부
- 원본 입력 mapping을 변경하지 않는지

### 12.2 데이터 품질 테스트

- 운동 파라미터가 모두 있는 행 비율
- fallback으로 내려간 행 비율
- `release_error_ft`의 중앙값과 큰 이상치
- 비행시간과 릴리스/도착 속도의 비정상 범위
- 구종별 표본 수

이 범위는 야구 규칙의 절대 제한이 아니라 오류 탐지용으로 사용한다.

### 12.3 프런트엔드 테스트

- 고정 JSON에서 tube 시작·종점
- 포수/투수 시점 좌우 방향
- 구종 필터와 전체 토글
- 카메라 프리셋
- 빈 데이터·API 오류·WebGL 미지원 화면
- 모바일에서 컨트롤이 Canvas를 가리지 않는지
- 색상 없이도 구종 코드와 라벨을 확인할 수 있는지

### 12.4 시각 회귀 기준

같은 fixture와 고정 카메라로 다음 장면을 저장한다.

- umpire 시점
- pitcher 시점
- side 시점
- 구종 한 개만 표시
- 여러 구종 표시
- 터널·히트맵을 추가한 경우 각각 ON 상태

---

## 13. 주요 위험과 대응

| 위험 | 나타나는 현상 | 대응 |
|---|---|---|
| `pfx` ft/inch 혼동 | 너무 휘거나 거의 직선 | Python 입력 기본 ft, 변환 옵션 명시 |
| x축 이중 반전 | 슬라이더가 반대로 움직임 | 변환은 Python 한 곳에서만 수행 |
| 프런트 재계산 | Python과 화면이 다름 | 프런트는 points만 렌더링 |
| 평균값 과해석 | 실제 없던 대표선 생성 | 평균 기반 표시, 개별 복원 후 중앙값 사용 |
| 결측 기본값 | 틀린 궤적이 정상처럼 보임 | 해당 행 제외와 제외 사유 기록 |
| 대용량 JSON | 로딩·렌더 저하 | 필터 후 생성, 대표선 또는 최근 N개만 전달 |
| WebGL 성능 | 모바일 FPS 저하 | DPR 제한, 숨긴 구종 unmount, geometry 재사용 |
| 원본 데이터 수정 | 재현성 손상 | `data/raw/`는 읽기 전용으로 취급 |
| 큰 산출물 커밋 | 저장소 비대화 | `.gitignore` 규칙과 `data/processed/` 정책 준수 |
| 엔진 버전 변경 | 이전 화면과 모양이 달라짐 | `model_version`과 fixture 회귀 테스트 |

---

## 14. 팀 작업 분담과 권장 이슈 순서

| 순서 | 작업 | 담당 역할 | 선행 조건 |
|---:|---|---|---|
| 1 | 실제 Statcast 표본 선정·단위 확인 | 데이터/분석 | 없음 |
| 2 | 실제 데이터 품질 리포트와 fixture | 데이터/분석 | 1 |
| 3 | 대표 궤적 집계·formatter | Python | 2 |
| 4 | 화면 기술과 전달 방식 결정 | 팀 전체 | 3의 JSON 예시 |
| 5 | 최소 3D viewer | 프런트엔드 | 4 |
| 6 | Python↔화면 좌표 통합 테스트 | Python+프런트 | 5 |
| 7 | 카메라·필터 | 프런트엔드 | 6 |
| 8 | 터널·히트맵 등 선택 기능 | 프런트엔드+분석 | 7 |
| 9 | 성능·접근성·회귀 검증 | QA/팀 전체 | 8 |

모든 변경은 기능 브랜치와 PR을 사용한다. 새 라이브러리를 추가하면 프로젝트의
의존성 파일도 함께 갱신한다. API 키나 개인 정보는 코드와 fixture에 넣지 않는다.

---

## 15. 회의에서 정할 네 가지

구현 전에 아래 네 항목만 결정하면 된다. 권장 기본값도 함께 적었다.

| 결정 | 권장 기본값 | 이유 |
|---|---|---|
| 첫 화면 범위 | 대표 궤적 + 카메라 + 구종 필터 | 핵심 가치 검증에 충분 |
| 데이터 전달 | fixture로 시작, 이후 API | 화면과 서버를 동시에 만들 필요 없음 |
| 프런트엔드 | 팀의 기존 표준이 없으면 별도 논의 | 현재 저장소에는 선택 근거가 없음 |
| 대표 궤적 | 개별 복원 후 진행률별 중앙값 | 단순 필드 평균보다 왜곡이 적음 |

히트맵, 터널 모드, 실제 투구 애니메이션은 MVP 이후로 둔다.

---

## 16. 다른 팀원에게 3분 안에 설명하기

### 1분: 무엇을 만드는가

“Statcast의 공 위치·속도·가속도 값으로 투구가 릴리스부터 홈까지 이동한 경로를
여러 개의 3D 점으로 복원하고, 나중에 웹 화면에서 선으로 보여 주는 기능입니다.”

### 1분: 계산과 화면을 왜 나누는가

“Python이 데이터 단위와 물리 계산을 한 번만 책임지고, 웹 화면은 결과 점을
그리기만 합니다. 그래야 분석 코드와 화면이 서로 다른 궤적을 만드는 문제를
막을 수 있습니다.”

### 1분: 지금 어디까지 되었는가

“Python 복원 함수와 기본 테스트는 끝났습니다. 다음은 실제 데이터로 좌우 방향과
오차를 확인하고, 구종별 대표 궤적 JSON을 만든 뒤, 최소 3D 화면을 붙이는 순서입니다.”

---

## 17. 최종 완료 기준

### 데이터와 계산

- [ ] 실제 우투·좌투 표본에서 방향과 종점을 검증했다.
- [ ] 입력·출력의 단위와 좌표계가 API 또는 JSON에 포함된다.
- [ ] 운동 파라미터 사용과 fallback 사용을 구분할 수 있다.
- [ ] 구종 대표 궤적의 표본 수와 집계 방법이 표시된다.
- [ ] 대용량 원본과 산출물을 Git에 올리지 않는다.

### 코드

- [x] 계산은 React/Three.js에 의존하지 않는 Python 함수다.
- [x] 동일 입력은 동일 결과를 만든다.
- [x] 기본 단위 테스트가 있다.
- [ ] 실제 데이터 fixture 회귀 테스트가 있다.
- [ ] formatter/API가 같은 기준 함수를 호출한다.

### 화면

- [ ] 프런트엔드에 별도 궤적 공식이 없다.
- [ ] 기준 fixture의 시작점·종점·좌우 방향이 일치한다.
- [ ] 로딩·오류·빈 데이터·WebGL 미지원 상태가 있다.
- [ ] 평균 기반 궤적임을 사용자가 확인할 수 있다.
- [ ] 모바일과 키보드 환경에서 핵심 기능을 사용할 수 있다.

### 협업

- [ ] 기능 브랜치와 PR 검토를 거쳤다.
- [ ] 새 의존성과 실행 방법이 README에 반영됐다.
- [ ] 계산 모델 변경 시 버전과 테스트 fixture도 갱신한다.

---

## 18. 최종 결론

이 프로젝트에서는 다른 프로젝트의 화면과 물리 엔진을 통째로 복사하지 않는다.
이미 만든 `src/visualization/pitch_trajectory.py`를 궤적 계산의 단일 기준으로 삼고,
실제 데이터 검증 → 대표 궤적 JSON → 최소 3D viewer → 선택 기능 순서로 결합한다.

이 순서를 지키면 프런트엔드 기술이나 API 방식이 나중에 바뀌어도 궤적 계산과
데이터 의미는 그대로 유지할 수 있다.
