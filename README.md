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
   git clone https://github.com/Yonsei-Sports-Analytics-Lab/9th-first-project-baseball-1.git
   cd 9th-first-project-baseball-1
   ```
2. **가상환경 생성 및 패키지 설치**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **원본 데이터 배치** — 아래 구글 드라이브에서 받아 `data/raw/{연도}/statcast_{연도}-{MM}.csv` 형태로 넣고, `fip_2021_2025.csv` 는 `data/raw/` 바로 아래에 둡니다. 자세한 규칙은 [`data/raw/README.md`](data/raw/README.md) 참고.
4. **`.env` 설정 (LLM API 키)** — 예시 파일을 복사해 프로젝트 루트에 `.env` 를 만들고 키를 채웁니다.
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
   * 키가 없어도 서버와 유사 투수 API(①)는 동작합니다. LLM 분석 API(②)만 `502` 오류를 돌려줍니다.
5. **실행**
   ```bash
   python main.py --k 6
   ```
   처음 실행하면 아래 준비를 마친 뒤 서버가 `http://127.0.0.1:8000` 에 뜹니다. 이미 만들어진 파일은 다시 만들지 않으므로 두 번째 실행부터는 바로 서버가 뜹니다. 브라우저에서 `http://127.0.0.1:8000/docs` 로 API 를 직접 호출해 볼 수 있고, [`docs/api_demo.html`](docs/api_demo.html) 을 열어 화면에서 확인할 수도 있습니다.
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

### ① `GET /{player_id}/{year}` — 유사 투수 (빠름)

```json
{
  "matched": true,
  "message": null,
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": { "player_id": 543037, "year": 2021 },
  "llm_url": "/660271/2023/llm"
}
```

### ② `GET /{player_id}/{year}/llm` — LLM 분석 (느림)

유사 투수는 서버가 다시 찾으므로 URL 에 넣지 않습니다. 같은 조합의 답변은 메모리에 캐시되어 두 번째 요청부터는 바로 응답합니다(`"cached": true`, 서버를 다시 켜면 비워짐).

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
