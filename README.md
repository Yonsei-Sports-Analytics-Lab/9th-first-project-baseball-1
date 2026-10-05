# ⚾ 패스트볼 레퍼토리 기반 유사 투수 탐색

Statcast 투구 데이터에서 **패스트볼(FF 포심 / SI 싱커 / FC 커터)** 만 뽑아, 체공시간 보정 무브먼트와 팔 각도로 투구를 클러스터링합니다. 이 결과로 **투수-시즌마다 어떤 유형의 패스트볼을 던지는지** 정리하고, 입력한 투수와 가장 비슷한 투수를 찾아 LLM 분석과 함께 API로 제공합니다.

---

## 🔄 전체 흐름

```
data/raw/{연도}/statcast_{연도}-{MM}.csv          (Baseball Savant 월별 원본)
        │  1. extract_fastball                    FF/SI/FC 만 추출, 필수 컬럼 결측 제거
        ▼
data/processed/{연도}_processed.csv
        │  2. compute_movement_reconciliation     체공시간 보정 무브먼트 ivb_ft, hb_ft 계산
        ▼
data/processed/{연도}_movement_reconciliation.csv
        │  3. fit_pitch_gmm                       모든 투구로 GMM(K개 클러스터) 적합
        ▼
data/processed/pitch_type_gmm_k{K}.joblib
        │  4. cluster_pitcher_repertoire          투구마다 클러스터 할당 → 투수-시즌별 최빈 클러스터·평균 구속
        ▼
data/processed/pitcher_clustered.json            {MLB ID: {연도: {average_velocity, cluster}}}
        │
        ▼
main.py (FastAPI 백엔드)
  GET /{player_id}/{year}         (빠름)
    → src/utils/find_nearest_pitcher : 가장 비슷한 (MLB ID, 연도) 찾기
  GET /{player_id}/{year}/llm     (느림)
    → src/utils/llm_client           : 두 투수-시즌을 LLM 으로 분석 (dict)
```

1~4단계는 `src/preprocessing/preprocess_pipeline.py` 가 순서대로 실행하며, `main.py` 는 서버를 띄우기 전에 이 파이프라인을 먼저 돌립니다.

---

## 📁 저장소 구조

```
.
├── main.py                        # 백엔드 서버 진입점 (전처리 → FastAPI 서버)
├── requirements.txt
├── data/
│   ├── raw/                       # 원본 Statcast CSV (git 미포함, 구글 드라이브로 공유)
│   └── processed/                 # 전처리·모델·클러스터 결과 (data_description.json 만 git 포함)
├── notebooks/                     # EDA·실험 노트북 (DBSCAN, GMM K 탐색)
├── src/
│   ├── preprocessing/             # 전처리 파이프라인 + GMM 적합·평가·클러스터 집계
│   ├── utils/                     # 유사 투수 탐색, LLM 클라이언트
│   ├── collection/                # 데이터 수집
│   ├── models/                    # 모델
│   └── visualization/             # 시각화
├── docs/                          # 분석 결과 문서
├── STATCAST_2021_03_변수설명서.md    # 원본 컬럼 설명
└── 체공시간_보정_무브먼트_계산_가이드.md  # ivb_ft / hb_ft 계산 방법
```

---

## 💻 시작하기

1. **저장소 클론**
   ```bash
   git clone --branch Euihan --single-branch https://github.com/Yonsei-Sports-Analytics-Lab/9th-first-project-baseball-1.git
   cd 9th-first-project-baseball-1
   ```
2. **가상환경 생성 및 패키지 설치**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **원본 데이터 배치** — 아래 구글 드라이브에서 받아 `data/raw/{연도}/statcast_{연도}-{MM}.csv` 형태로 넣고, `fip_2021_2025.csv` 는 `data/raw/` 바로 아래에 둡니다. 자세한 규칙은 [`data/raw/README.md`](data/raw/README.md) 참고.
4. **`.env` 설정 (선택: 생성형 AI 설명)** — 실제 AI 설명이 필요하면 예시 파일을 복사해 프로젝트 루트에 `.env` 를 만들고 키를 채웁니다.
   ```bash
   copy .env.example .env          # macOS/Linux: cp .env.example .env
   ```
   | 변수 | 필수 | 설명 |
   |---|---|---|
   | `GEMINI_API_KEY` | 둘 중 하나 | Gemini API 키 (무료) — https://aistudio.google.com/apikey |
   | `OPENAI_API_KEY` | 둘 중 하나 | OpenAI API 키 (유료) — https://platform.openai.com/api-keys. **둘 다 있으면 OpenAI 를 사용** |
   | `LLM_MODEL` | 선택 | 사용할 모델 이름. 비우면 제공자 기본 모델 |
   | `LLM_FALLBACK_MODELS` | 선택 | 기본 모델이 혼잡할 때 차례로 시도할 모델 (쉼표 구분). 비우면 기본 순서 |
   | `DATA_DRIVE_SECRET_LINK`, `SPORTS_API_KEY` | – | 템플릿 항목. 현재 코드에서는 사용하지 않음 |

   * `.env` 는 `.gitignore` 에 포함되어 있어 커밋되지 않습니다. **키를 코드·README·이슈·PR 에 절대 적지 마세요.** 새 변수가 필요하면 값 없이 이름만 `.env.example` 에 추가합니다.
   * 키가 없으면 분석 API(②)가 `502` 대신 Statcast 수치에 근거한 설명을 반환합니다. 이 답변은 **AI 생성이 아니라고 명시**됩니다. 생성형 AI 분석에는 유효한 API 키가 필요합니다.
5. **실행**
   ```bash
   python main.py --k 6
   ```
   처음 실행하면 아래 준비를 마친 뒤 서버가 `http://127.0.0.1:8000` 에 뜹니다. 이미 만들어진 파일은 다시 만들지 않으므로 두 번째 실행부터는 바로 서버가 뜹니다. 브라우저에서 서버 주소를 열면 [`frontend/`](frontend/README.md)의 PITCH TWIN 화면으로 이동하고, `http://127.0.0.1:8000/docs` 에서 API를 직접 호출할 수도 있습니다.
   1. 전처리 파이프라인 → `data/processed/pitcher_clustered.json` (원본 5개 연도 기준 수 분)
   2. 유사 투수 탐색용 프로필 → `data/processed/pitcher_profile.csv`
   3. LLM 입력용 구종 집계 → `data/processed/interim/pitch_arsenal.pkl` (약 1분)

### `main.py` 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--k` | `10` | GMM 클러스터 개수 K |
| `--force STAGE ...` | 없음 | 산출물이 있어도 다시 실행할 전처리 단계 (`extract` `movement` `fit` `cluster`) |
| `--skip-preprocess` | – | 전처리 없이 서버만 실행 |
| `--top-n` | `1` | `find_nearest_pitcher` 에 넘기는 `top_n` |
| `--host` / `--port` | `127.0.0.1` / `8000` | 서버 주소 |
| `--cors-origins` | `*` (모두 허용) | 브라우저 접근을 허용할 프론트엔드 주소 (쉼표로 구분) |

---

## 🌐 API

LLM 분석은 오래 걸리므로 API 를 두 개로 나눴습니다. 프론트엔드는 ① 을 받아 유사 투수를 먼저 보여 주고, 이어서 ② 를 호출하는 동안 로딩을 띄우면 됩니다. `player_id` 는 MLB(MLBAM) 선수 ID, `year` 는 시즌 연도입니다.

### ① `GET /{player_id}/{year}` — 유사 투수 + 선수 프로필 (빠름)

LLM 에 넘기는 것과 같은 두 선수의 프로필(구종별 스탯, 주 패스트볼)을 함께 돌려줍니다. LLM 을 부르지 않으므로 바로 응답합니다.

```json
{
  "matched": true,
  "message": null,
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": { "player_id": 668390, "year": 2025 },
  "llm_url": "/660271/2023/llm?rank=1",
  "cluster_map_url": "/cluster-map/660271/2023?rank=1",
  "profiles": {
    "input_pitcher":    { "pitcher_id": 660271, "player_name": "Ohtani, Shohei", "season": 2023, "throws": "R",
                          "primary_fastball": { "pitch_type": "FF", "velo_mph": 96.8, "ivb_in": 14.1, "hb_in": 4.1, "arm_angle_deg": 36.4, "...": "..." },
                          "arsenal": [ { "pitch_type": "ST", "pitch_name": "Sweeper", "usage_pct": 35.0, "velo_mph": 83.7,
                                         "whiff_pct": 35.9, "rv_per_100": 1.22, "...": "..." } ] },
    "similar_pitcher":  { "...": "input_pitcher 와 같은 구조" },
    "search_context":   { "cluster": 4, "input_fip": 4.0, "similar_fip": 3.9, "form_distance": 0.91, "...": "..." },
    "transfer_targets": [ { "pitch_type": "FC", "target_shape": { "velo_mph": 91.9, "ivb_in": 5.2, "hb_in": -5.6 }, "...": "..." } ]
  },
  "profile_error": null
}
```

* 필드 의미는 `src/utils/llm_client.py` 맨 위 설명과 같습니다 (HB 는 암사이드 +, RV/100 은 + 가 투수에게 좋음).
* 프로필을 만들지 못하면 `"profiles": null` 이고 `"profile_error"` 에 이유가 들어갑니다. 유사 투수 결과는 그대로 옵니다.
* 유사 투수가 없을 때(`"matched": false`)도 `profiles.input_pitcher` 는 채워지고 `similar_pitcher` 는 `null` 입니다.
* `?rank=2`처럼 순위를 지정하면 두 번째로 가까운 후보를 반환합니다. 생략하면 서버의 `--top-n` 값(기본 1)을 사용합니다.

### GMM 지도 `GET /cluster-map/{player_id}/{year}?rank=N`

기존 3변수 GMM의 모든 패스트볼 군집 중심·1.5표준편차 밀도 정보, 군집별 실제 투구
최대 180개, 비교 투수 두 명의 시즌 FF·SI·FC 전체 평균 IVB·HB·팔 각도를 반환합니다.
전체 2021–2025년 패스트볼에 군집 번호를 매겨 비율을 계산하며, 첫 호출은
`data/processed/cluster_map_k{K}_v2.json` 캐시 생성 때문에 느릴 수 있습니다.
화면에서는 각 군집의 실제 투구 표본을 IVB–HB 2D 점으로만 나타내고, 두 투수의
시즌 평균을 점 하나씩 표시합니다. 점 라벨에는 투수 이름만 나타내고 팔 각도는
옆의 상세 정보에서 확인할 수 있습니다. 군집 번호는 투구별 3변수 GMM 결과의
최빈값이므로 평균점이 다른 군집의 색 점 근처에 있어도 모순이 아닙니다.
투수 평균점은 단일 실제 투구가 아닙니다.

### 투수 검색 `GET /pitchers`

프런트엔드 이름 자동완성용 API입니다. `query`(이름 또는 MLB ID), `year`, `limit`을 선택적으로 받으며,
`player_id`, 화면용 `player_name`, 보유 `seasons`를 반환합니다.

### ② `GET /{player_id}/{year}/llm` — LLM 분석 (느림)

유사 투수는 서버가 다시 찾으므로 URL 에 넣지 않습니다. 같은 조합의 답변은 메모리에 캐시되어 두 번째 요청부터는 바로 응답합니다(`"cached": true`, 서버를 다시 켜면 비워짐).
1단계와 같은 `rank` 쿼리를 전달해야 동일한 비교 대상의 분석을 받을 수 있습니다.

```json
{
  "matched": true,
  "message": null,
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": { "player_id": 543037, "year": 2021 },
  "llm":     { "...": "llm_client 가 돌려준 dict" },
  "cached":  false
}
```

### 유사 투수가 없을 때

두 API 모두 오류가 아닌 `200` 으로 아래처럼 응답하고, LLM 은 호출하지 않습니다. 프론트엔드는 `matched` 로 구분해 `message` 를 보여 주면 됩니다.

```json
{
  "matched": false,
  "message": "조건에 맞는 유사 투수를 찾지 못했습니다.",
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": null,
  "llm_url": null
}
```

(`/llm` 에서는 `"llm_url"` 대신 `"llm": null` 이 옵니다.)

| 상태 코드 | 의미 |
|---|---|
| `200` | 성공 (유사 투수가 없을 때도 `200`, `"matched": false`) |
| `404` | `pitcher_clustered.json` 에 없는 (ID, 연도) — 응답에 그 선수의 가능한 연도가 함께 옴 |
| `422` | ID·연도가 숫자가 아니거나 범위를 벗어남 |
| `500` | `find_nearest_pitcher` 실행 오류 또는 반환 형식 오류 |
| `502` | (`/llm`) `llm_client` 호출 오류 또는 dict 가 아닌 반환 |
| `503` | (`/llm`) `src/utils/llm_client.py` 를 아직 불러올 수 없음 |

### `GET /health`

서버 상태, K, 로드된 투수 수, LLM 캐시 개수를 돌려줍니다.

---

## 📚 문서

- [`체공시간_보정_무브먼트_계산_가이드.md`](체공시간_보정_무브먼트_계산_가이드.md) — `ivb_ft`, `hb_ft` 계산 수식과 절차
- [`STATCAST_2021_03_변수설명서.md`](STATCAST_2021_03_변수설명서.md) — 원본 Statcast 컬럼 설명
- [`data/processed/README.md`](data/processed/README.md) — 산출물 파일과 JSON 형식
- [`src/preprocessing/README.md`](src/preprocessing/README.md) — 전처리 모듈별 사용법

## 3D 투구 궤적 시각화

비교 화면은 기존 React Three Fiber 뷰어를 사용합니다. 두 투수-시즌의 원본
Statcast 정규시즌 CSV에서 구종별 최대 12구를 표본으로 선택하고, 기존
`pitch_trajectory.py`로 3D 좌표를 복원합니다. 첫 조회는 원본 파일을 읽으므로
느릴 수 있지만 이후에는 `data/processed/trajectory_cache/`를 재사용합니다.
투수·구종별 시즌 전체 `plate_x`·`plate_z`를 0.25ft 간격으로 집계해 최빈
도착 구간을 찾고, 그 구간 중심에 가장 가까운 실제 투구를 표본에 포함합니다.
비교 화면은 기본적으로 이 대표 투구 1개만 그리며, 필요할 때 `전체 표본 보기`로
전환할 수 있습니다. 최빈 구간이 동률이면 구간 중심 부근에 더 밀집한 쪽을 택합니다.
궤적 색은 구종별로, 실선·점선은 두 투수별로 구분합니다. 끝점은 측정된
`plate_x`·`plate_z`를 사용하며, 흰색 스트라이크 존 테두리는 타자별 판정이
아닌 고정된 비교 가이드입니다.
비교 화면에서는 각 투수의 정규시즌 구사율이 10% 이상인 구종만 보여 줍니다.
군집·변화구 분석 카드에는 기존 3변수 GMM의 모든 군집을 IVB–HB 평면에 투영한
2D 지도도 표시합니다. 타원 없이 군집당 실제 투구 최대 180개를 점으로
보여 주며, 두 투수는 각 시즌 FF·SI·FC 전체 평균을 점 하나씩 표시합니다.
점 라벨에는 투수 이름만, 팔 각도 평균은 상세 정보에 표기합니다.
두 투수의 지도 마커는 군집 색 대신 흰색 채움/어두운 채움·흰 테두리로 구분합니다.
첫 지도 요청은 전체 데이터를 스캔해 로컬 캐시를 생성하므로 느릴 수 있습니다.
뷰어 코드를 수정한 뒤에는 `src/visualization/pitch_3d`에서 `npm ci`와
`npm run build:comparison`을 실행해 `frontend/three-viewer.*`를 갱신합니다.

`data/processed`의 `data_[설명].csv` 파일을 투수별 3D 궤적 데이터로 변환할 수
있습니다.

```bash
python3 -m src.visualization.dashboard_formatter --list-pitchers
python3 -m src.visualization.dashboard_formatter --pitcher "Shohei Ohtani"
```

변환기는 실제 Statcast 운동 파라미터를 우선 사용하며, 결과는
`src/visualization/pitch_3d/public/pitch-data.json`에 생성됩니다. React 뷰어의
연결 방법은 `src/visualization/pitch_3d/README.md`를 참고하세요.

---

## ⚠️ 협업 규칙

* **대용량 데이터 업로드 금지:** `data/raw/`, `data/processed/` 의 CSV·모델 파일은 GitHub 에 올리지 않습니다(`.gitignore` 로 제외). 원본은 구글 드라이브로 공유하고, 전처리 결과는 파이프라인으로 다시 만듭니다.
* **보안 정보 노출 주의:** API Key(LLM 키 포함)는 코드에 직접 쓰지 말고 `.env` 에 두세요. `.env` 는 커밋하지 않고, 필요한 변수 이름만 `.env.example` 에 적습니다.
* **Main 브랜치 직접 Push 금지:** 작업 브랜치(`feat/...`)에서 작업한 뒤 Pull Request 로 리뷰를 거쳐 병합합니다.
* **환경 동기화:** 새 라이브러리를 설치하면 `requirements.txt` 를 갱신해 커밋합니다. Windows PowerShell 에서 `pip freeze > requirements.txt` 를 쓰면 UTF-16 으로 저장되므로 아래 명령을 권장합니다.
  ```powershell
  pip freeze | Out-File -Encoding utf8 requirements.txt
  ```
* **이슈 트래킹:** 새 작업을 시작하거나 버그를 발견하면 템플릿에 맞춰 `Issue` 를 먼저 등록합니다.

---

## 🔗 구글 드라이브 (원본 데이터)
https://drive.google.com/drive/folders/1uxGd0kggrNSZbuXRMXHij4qSTAYBeocL?usp=sharing
