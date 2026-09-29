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
  GET /{player_id}/{year}
    → src/utils/find_nearest_pitcher : 가장 비슷한 (MLB ID, 연도) 찾기
    → src/utils/llm_client           : 두 투수-시즌을 LLM 으로 분석 (dict)
    → 프론트엔드로 JSON 응답
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
3. **원본 데이터 배치** — 아래 구글 드라이브에서 받아 `data/raw/{연도}/statcast_{연도}-{MM}.csv` 형태로 넣습니다. 자세한 규칙은 [`data/raw/README.md`](data/raw/README.md) 참고.
4. **실행**
   ```bash
   python main.py --k 6
   ```
   처음 실행하면 전처리(원본 5개 연도 기준 수 분 소요)를 끝낸 뒤 서버가 `http://127.0.0.1:8000` 에 뜹니다. 이미 만들어진 산출물은 다시 만들지 않으므로 두 번째 실행부터는 바로 서버가 뜹니다. 브라우저에서 `http://127.0.0.1:8000/docs` 로 API 를 직접 호출해 볼 수 있습니다.

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

### `GET /{player_id}/{year}`

`player_id` 는 MLB(MLBAM) 선수 ID, `year` 는 시즌 연도입니다.

```json
{
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": { "player_id": 543037, "year": 2021 },
  "llm":     { "...": "llm_client 가 돌려준 dict" }
}
```

| 상태 코드 | 의미 |
|---|---|
| `200` | 성공 |
| `404` | `pitcher_clustered.json` 에 없는 (ID, 연도) — 응답에 그 선수의 가능한 연도가 함께 옴 / 유사 투수를 찾지 못함 |
| `422` | ID·연도가 숫자가 아니거나 범위를 벗어남 |
| `500` | `find_nearest_pitcher` 실행 오류 또는 반환 형식 오류 |
| `502` | `llm_client` 호출 오류 또는 dict 가 아닌 반환 |
| `503` | `src/utils` 의 모듈을 아직 불러올 수 없음 |

### `GET /health`

서버 상태, K, 로드된 투수 수를 돌려줍니다.

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
