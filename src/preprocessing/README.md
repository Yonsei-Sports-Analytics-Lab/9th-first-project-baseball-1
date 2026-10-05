# 🧹 Preprocessing (전처리 · 1차 클러스터링)

Statcast 원본에서 패스트볼을 뽑아 **체공시간 보정 무브먼트** 를 계산하고, **GMM 으로 투구를 클러스터링** 한 뒤 **투수-시즌별 최빈 클러스터와 평균 구속** 을 JSON 으로 저장하는 모듈입니다.

## 🔄 파이프라인

| 순서 | 모듈 | 입력 → 산출물 (`data/processed/`) |
|---|---|---|
| 1 | `extract_fastball.py` | `data/raw/{연도}/statcast_{연도}-{MM}.csv` → `{연도}_processed.csv` |
| 2 | `compute_movement_reconciliation.py` | `{연도}_processed.csv` → `{연도}_movement_reconciliation.csv` (+ `reference_flight_times.json`) |
| 3 | `fit_pitch_gmm.py` | `{연도}_movement_reconciliation.csv` → `pitch_type_gmm_k{K}.joblib` |
| 4 | `cluster_pitcher_repertoire.py` | 무브먼트 CSV + GMM 모델 → 클러스터 JSON |
| – | `preprocess_pipeline.py` | 1~4 를 순서대로 실행 |
| – | `evaluate_pitch_gmm.py` | 저장된 GMM 모델의 군집 품질 지표 출력 |
| – | `load_movement_data.py` | 무브먼트 CSV 탐색·로드 (3, 4, 평가 모듈이 공통으로 사용) |

### 전체 실행

```bash
python src/preprocessing/preprocess_pipeline.py --k 6 --cluster-output pitcher_clustered.json
python src/preprocessing/preprocess_pipeline.py --k 6 --dry-run            # 실행될 단계만 확인
python src/preprocessing/preprocess_pipeline.py --k 6 --force fit cluster   # 강제로 다시 실행
```

**건너뛰기 규칙**

* **`extract`, `movement`:** 연도별 산출물이 있으면 그 연도는 건너뛰고, **없는 연도만** 처리합니다. `reference_flight_times.json` 이 있으면 기준 체공시간을 재사용해, 새 연도도 기존 연도와 같은 기준으로 보정합니다.
* **`fit`:** `pitch_type_gmm_k{K}.joblib` 이 있으면 건너뜁니다.
* **`cluster`:** 결과 JSON 이 있으면 건너뜁니다. 단, 그 JSON 을 만든 모델과 지금 모델이 다르면(K 변경, `fit` 재실행) 다시 만듭니다. 어떤 모델로 만들었는지는 `pipeline_state.json` 에 기록됩니다.
* 상위 단계가 새로 실행됐는데 하위 산출물이 있어 건너뛰면 경고가 나옵니다. 새 데이터를 반영하려면 `--force` 를 붙이세요.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--k` | `10` | GMM 클러스터 개수 |
| `--years` | 모든 연도 | 처리할 연도 |
| `--force STAGE ...` | – | `extract` `movement` `fit` `cluster` 중 다시 실행할 단계 |
| `--dry-run` | – | 실행하지 않고 계획만 출력 |
| `--cluster-output` | `pitcher_repertoire_clusters_k{K}.json` | 클러스터 JSON 경로 또는 파일명 (`main.py` 는 `pitcher_clustered.json`) |
| `--fit-sample` | `200000` | GMM 적합에 쓸 표본 수 (`0` 이면 전체). 클러스터 할당은 항상 모든 투구에 함 |
| `--min-pitches` | `200` | JSON 에 포함할 투수-시즌 최소 투구 수 |
| `--raw-dir`, `--processed-dir` | `data/raw`, `data/processed` | 입출력 폴더 |

## 📄 모듈별 설명

### 1. `extract_fastball.py`
월별 원본을 연도 단위로 합치면서 FF/SI/FC 만 남기고, 필수 물리량 컬럼에 결측이 있는 행을 제거합니다. 파일을 청크 단위로 읽어 메모리를 적게 씁니다.
```bash
python src/preprocessing/extract_fastball.py --years 2024 2025 --no-overwrite
```

### 2. `compute_movement_reconciliation.py`
`pfx_x`, `pfx_z` 를 inch 로 바꾸고 좌완·우완의 수평 방향을 **암사이드 +** 로 통일한 뒤, 릴리스~홈플레이트 체공시간 `T` 로 보정합니다.
`ivb_ft = ivb_raw × (T_ref / T)²`, `hb_ft = hb_arm_side × (T_ref / T)²` 입니다. `T_ref` 는 구종별 기준 체공시간(2021~2023 중앙값)이며, 자세한 수식은 루트의 `체공시간_보정_무브먼트_계산_가이드.md` 에 있습니다.
```bash
python src/preprocessing/compute_movement_reconciliation.py --reference-in data/processed/reference_flight_times.json
```

### 3. `fit_pitch_gmm.py`
`ivb_ft`, `hb_ft`, `arm_angle` 을 표준화한 뒤 GMM(`covariance_type="full"`)을 적합합니다. 각 성분이 하나의 "패스트볼 유형" 입니다. 표준화기와 GMM 을 `PitchTypeGMM` 객체 하나로 묶어 joblib 으로 저장합니다.
```bash
python src/preprocessing/fit_pitch_gmm.py --k 6
```
* `PitchTypeGMM.predict(df)` → 투구별 클러스터 번호, `predict_proba(df)` → 투구별 소속 확률
* `load_model(path)` 로 불러옵니다. 모델은 `src.preprocessing.fit_pitch_gmm.PitchTypeGMM` 클래스 경로로 저장되므로, 이 모듈을 다른 이름으로 복사해 쓰면 불러올 수 없습니다.

### 4. `cluster_pitcher_repertoire.py`
모든 투구에 클러스터를 붙인 뒤 `(pitcher, game_year)` 로 묶고, **그 시즌 가장 많이 던진
구종(주 패스트볼)의 투구만 남겨서**
* `cluster`: 주 패스트볼 투구가 가장 많이 속한 클러스터 (동률이면 번호가 작은 쪽)
* `average_velocity`: 주 패스트볼의 평균 `release_speed`

를 구해 `{MLB ID: {연도: {"average_velocity", "cluster"}}}` 형식으로 저장합니다. 형식은 `data/processed/README.md` 를 참고하세요.

구종을 섞지 않는 이유: 포심 55% / 싱커 45% 를 던지는 투수의 최빈 클러스터는 사실상 동전던지기가 되어 같은 투수라도 해마다 다른 클러스터로 튑니다. `--min-pitches` 도 **주 패스트볼 투구 수** 기준이며, 거르기 전 전체 패스트볼 수는 집계표의 `n_pitches_all` 에 남습니다.
```bash
python src/preprocessing/cluster_pitcher_repertoire.py --model-in data/processed/pitch_type_gmm_k6.joblib --output data/processed/pitcher_clustered.json
```
`--model-in` 없이 실행하면 GMM 을 직접 적합하고 모델도 저장합니다.

### `evaluate_pitch_gmm.py`
저장된 모델로 모든 투구에 클러스터를 다시 붙이고 품질 지표를 출력합니다. 여러 K 를 한 표로 비교할 수 있습니다.
```bash
python src/preprocessing/evaluate_pitch_gmm.py --k 3 6 10 --output data/processed/gmm_metrics.json
```
* 실루엣(표본 30,000개로 3회 반복), 데이비스-볼딘, 칼린스키-하라바즈
* 평균 로그우도, BIC, AIC
* 평균 최대 소속 확률, 경계 투구 비율(최대 확률 < 0.6), 정규화 엔트로피
* 기존 `pitch_type` 과의 ARI/NMI — 높다고 좋은 지표가 아니라, 기존 FF/SI/FC 를 얼마나 그대로 재현했는지를 봅니다
* 클러스터별 중심·크기·확신도·실루엣·주요 구종

### `load_movement_data.py`
`find_movement_files()` 로 연도별 무브먼트 CSV 를 찾고, `load_pitch_data()` 로 필요한 컬럼만 읽어 하나의 DataFrame 으로 합칩니다. 문자열 컬럼은 `category` 로 바꿔 메모리를 줄입니다.

## 🐍 코드에서 사용하기

모든 모듈은 CLI 외에 함수로도 호출할 수 있습니다.

```python
from src.preprocessing.preprocess_pipeline import run_pipeline
from src.preprocessing.fit_pitch_gmm import load_model
from src.preprocessing.cluster_pitcher_repertoire import run as cluster_run

run_pipeline(k=6, force=["cluster"], cluster_output="pitcher_clustered.json")

model = load_model("data/processed/pitch_type_gmm_k6.joblib")
seasons, model, pitches = cluster_run(model=model, save_json=False)
```

CLI 옵션과 함수 인자는 이름이 조금 다릅니다. `--fit-sample` 은 `fit_sample`, `--no-save-model` 은 `save_gmm=False` 에 해당하고, CLI 의 `--fit-sample 0` 은 함수에서 `fit_sample=None` 입니다.

## ⚠️ 작성 규칙

* **산출물 위치:** 결과는 `data/processed/` 에 저장합니다. 파일명 규칙은 `data/processed/README.md` 를 따릅니다.
* **대용량 처리:** 연도별 CSV 가 200~330MB 이므로 필요한 컬럼만 읽고(`usecols`), 청크 단위로 처리합니다.
* **중간 실패 대비:** CSV 는 임시 파일(`.tmp`)에 먼저 쓴 뒤 완료되면 교체합니다. 중간에 실패해도 기존 결과가 깨지지 않습니다.
