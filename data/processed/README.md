# 📂 Processed Data (전처리 결과)

`src/preprocessing/` 의 전처리 파이프라인과 `src/utils/find_nearest_pitcher.py` 가 만든 **중간 데이터, GMM 모델, 투수-시즌 클러스터 결과, 유사 투수 탐색용 프로필** 이 저장되는 폴더입니다.

## ⚠️ 작업 규칙

1. **직접 수정 금지:** 이 폴더의 파일은 엑셀 등으로 열어 고치지 않습니다. 모든 변경은 코드로 추적 가능해야 합니다.
2. **재현 가능성:** 파일이 지워져도 `python main.py` 를 실행하면 없는 파일만 다시 만들어집니다.
3. **git 에 올리지 않음:** `.gitignore` 에 의해 `README.md`, `data_description.json` 을 제외한 모든 파일은 커밋되지 않습니다.

## 📄 파일 목록

| 파일 | 만드는 코드 | 내용 |
|---|---|---|
| `{연도}_processed.csv` | `extract_fastball` | 월별 원본을 연도로 합치고 FF/SI/FC 만 남긴 투구 (필수 컬럼 결측 행 제거) |
| `{연도}_movement_reconciliation.csv` | `compute_movement_reconciliation` | 위 파일 + 체공시간 보정 무브먼트 컬럼 (`ivb_ft`, `hb_ft` 등) |
| `reference_flight_times.json` | `compute_movement_reconciliation` | 구종별 기준 체공시간 (학습연도 2021~2023 중앙값). 있으면 새 연도 처리 때 재사용 |
| `pitch_type_gmm_k{K}.joblib` | `fit_pitch_gmm` | 1차 클러스터링 GMM 모델 (표준화기 포함) |
| `pitcher_clustered.json` | `cluster_pitcher_repertoire` | 투수-시즌별 최빈 클러스터와 평균 구속 — **`main.py` 와 `find_nearest_pitcher` 가 쓰는 파일** |
| `pitcher_repertoire_clusters_k{K}.json` | `cluster_pitcher_repertoire` | 위와 같은 형식. 파이프라인·모듈을 단독 실행할 때의 기본 파일명 |
| `pipeline_state.json` | `preprocess_pipeline` | 클러스터 JSON 을 어떤 모델로 만들었는지 기록 (K 가 바뀌면 다시 만들기 위해) |
| `pitcher_profile.csv` | `find_nearest_pitcher.build_profile` | 유사 투수 탐색용 투수-시즌 프로필 (클러스터 + 투구 폼 + FIP) |
| `data_description.json` | (수동 작성) | 클러스터 JSON 형식 예시 — git 에 포함 |

체공시간 보정 무브먼트의 계산 방법은 루트의 [`체공시간_보정_무브먼트_계산_가이드.md`](../../체공시간_보정_무브먼트_계산_가이드.md) 를 참고하세요.

## 🧾 `pitcher_clustered.json` 형식

```json
{
  "660271": {
    "2023": { "average_velocity": 100.0, "cluster": 3 },
    "2024": { "average_velocity": 99.9, "cluster": 3 }
  }
}
```

* **키:** MLB(MLBAM) 선수 ID(Statcast `pitcher` 컬럼) → 시즌 연도. JSON 키라서 둘 다 문자열입니다.
* **`cluster`:** 그 투수-시즌의 투구가 가장 많이 속한 GMM 클러스터 번호 (0 ~ K-1). 동률이면 번호가 작은 쪽.
* **`average_velocity`:** 그 투수-시즌 패스트볼(FF/SI/FC)의 평균 `release_speed` (mph, 소수점 첫째 자리).
* 투구가 **200구 미만인 투수-시즌은 제외** 됩니다 (`--min-pitches` 로 변경 가능).
* 클러스터 번호는 모델마다 의미가 다릅니다. K 나 모델이 바뀌면 같은 번호라도 다른 유형입니다.

## 🧾 `pitcher_profile.csv` 형식

`pitcher_clustered.json` 의 투수-시즌마다 한 행입니다. 투구 폼 값이 없는 투수-시즌은 빠집니다.

| 컬럼 | 출처 | 설명 |
|---|---|---|
| `player_id`, `game_year` | 클러스터 JSON | MLB ID, 시즌 |
| `average_velocity`, `cluster` | 클러스터 JSON | 평균 구속, 최빈 클러스터 |
| `release_pos_x_arm` | 원본 Statcast | 릴리스 좌우 위치 평균 (ft, **암사이드 +** 로 좌우완 통일) |
| `release_pos_z` | 원본 Statcast | 릴리스 높이 평균 (ft) |
| `release_extension` | 원본 Statcast | 익스텐션 평균 (ft) |
| `arm_angle` | 원본 Statcast | 팔 각도 평균 (°) |
| `p_throws`, `player_name` | 원본 Statcast | 투구 손(최빈값), 선수 이름 (확인용) |
| `FIP`, `IP` | `data/raw/fip_2021_2025.csv` | 수비 무관 평균자책점, 이닝 |
| `*_z` | 계산 | 위 투구 폼 4개를 전체 투수-시즌 기준으로 표준화한 값 (유사도 거리 계산용) |

투구 폼 평균은 패스트볼만이 아니라 **원본의 모든 구종** 투구로 계산합니다.

## 🔄 다시 만들기

`python main.py` 를 실행하면 아래 순서로 **필요한 파일만** 만듭니다.

1. 전처리 파이프라인 (`extract` → `movement` → `fit` → `cluster`) — 산출물이 있는 단계는 건너뜀
2. `pitcher_profile.csv` — **없거나, `pitcher_clustered.json` 이 프로필보다 나중에 만들어졌으면** 다시 생성

```bash
python main.py --k 6                          # 없는 산출물만 생성 후 서버 시작
python main.py --k 6 --force fit cluster      # GMM·클러스터를 다시 만들고, 프로필도 자동으로 다시 생성
```

전처리만 따로 실행할 때:

```bash
python src/preprocessing/preprocess_pipeline.py --k 6 --cluster-output pitcher_clustered.json --dry-run
python -m src.utils.find_nearest_pitcher      # pitcher_profile.csv 만 다시 생성
```

* 원본 Statcast 나 `fip_2021_2025.csv` 를 교체한 경우에는 프로필이 자동으로 갱신되지 않습니다. `pitcher_profile.csv` 를 지우고 다시 실행하세요.
* 자세한 전처리 옵션은 [`src/preprocessing/README.md`](../../src/preprocessing/README.md) 를 참고하세요.
