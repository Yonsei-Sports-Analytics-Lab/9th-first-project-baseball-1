# 🛠️ Utils (유사 투수 탐색 · LLM 클라이언트)

백엔드 API(`main.py` 의 `GET /{player_id}/{year}`)가 호출하는 모듈을 두는 폴더입니다.

| 파일 | 상태 | 역할 |
|---|---|---|
| `find_nearest_pitcher.py` | ✅ 구현 | 입력한 투수-시즌과 비슷한 투수-시즌 `(MLB ID, 연도)` 찾기 |
| `llm_client.py` | 🚧 작업 중 | 두 투수-시즌을 받아 LLM 분석(dict) 반환 |

---

## `find_nearest_pitcher.py`

### 매칭 조건

입력한 투수-시즌(기준)에 대해 아래 조건을 **모두** 만족하는 투수-시즌을 후보로 두고, 투구 폼이 가까운 순으로 정렬합니다.

1. **같은 클러스터:** `pitcher_clustered.json` 의 `cluster` 가 같음
2. **비슷한 구속:** 평균 구속 차이가 `velocity_tol`(기본 ±2.0 mph) 이내
3. **더 좋은 성적:** `FIP` 가 기준보다 낮음
4. **다른 선수:** 같은 선수는 연도와 상관없이 제외
5. (선택) **최소 이닝:** `IP >= min_ip`

거리는 투구 폼 4개(릴리스 좌우·높이, 익스텐션, 팔 각도)를 표준화한 값의 유클리드 거리이며, **선수 한 명당 가장 가까운 시즌 하나만** 남깁니다.

### 주요 함수

| 함수 | 설명 |
|---|---|
| `find_nearest_pitcher(pitcher_id, year, rank=1, velocity_tol=2.0, min_ip=None, profile=None)` | `rank` 번째로 비슷한 투수-시즌을 `(MLB ID, 연도)` 튜플로 반환. 없으면 `None` |
| `rank_candidates(pitcher_id, year, velocity_tol=2.0, min_ip=None, profile=None)` | 조건을 통과한 후보 전체를 거리순 DataFrame 으로 반환 (노트북 확인용) |
| `build_profile(cluster_file, fip_file, save=True)` | 원본 Statcast + `pitcher_clustered.json` + FIP 로 `data/processed/pitcher_profile.csv` 생성 |
| `load_profile(path, reload=False)` | 프로필 CSV 를 한 번만 읽어 메모리에 보관 (`reload=True` 로 다시 읽기) |
| `find_raw_files(raw_dir)` | `data/raw/{연도}/statcast_{연도}-{MM}.csv` 목록 (임시 파일 제외) |

### `None` 이 반환되는 경우

* 기준 투수-시즌이 프로필에 없음 (투구 폼 값이 없어 빠진 경우 포함)
* 기준 투수-시즌의 FIP 가 없음
* 조건을 만족하는 후보가 없음
* `rank` 가 1보다 작거나 후보 수보다 큼

### 필요한 파일

| 파일 | 설명 |
|---|---|
| `data/raw/{연도}/statcast_{연도}-{MM}.csv` | 투구 폼 계산용 원본 (`build_profile` 실행 때만 필요) |
| `data/raw/fip_2021_2025.csv` | `player_id`, `game_year`, `FIP`, `IP` 컬럼 |
| `data/processed/pitcher_clustered.json` | 전처리 파이프라인 결과 (클러스터, 평균 구속) |
| `data/processed/pitcher_profile.csv` | `build_profile` 결과. 매칭은 이 파일만 읽음 |

### 프로필 생성

`main.py` 가 서버를 띄우기 전에 자동으로 처리합니다.

* `pitcher_profile.csv` 가 **없으면** 생성합니다.
* `pitcher_clustered.json` 이 **프로필보다 나중에 만들어졌으면**(K 변경, `--force cluster` 등) 다시 생성합니다.
* 그 외에는 건너뜁니다. 원본이나 FIP 파일을 교체했다면 `pitcher_profile.csv` 를 지우고 다시 실행하세요.

직접 만들 때는 프로젝트 루트에서 실행합니다 (전체 원본 기준 수십 초).

```bash
python -m src.utils.find_nearest_pitcher
```

```python
from src.utils.find_nearest_pitcher import find_nearest_pitcher, rank_candidates

find_nearest_pitcher(543037, 2023)              # -> (MLB ID, 연도) 또는 None
find_nearest_pitcher(543037, 2023, rank=2)      # 두 번째로 비슷한 투수
rank_candidates(543037, 2023, min_ip=50).head() # 후보 전체 확인
```

---

## `llm_client.py` — 🚧 작업 중

`main.py` 는 아래 형태를 기준으로 호출합니다.

```python
from src.utils.llm_client import llm_client
answer = llm_client((player_id, year), (nearest_id, nearest_year))   # -> dict
```

| 인자 | 타입 | 설명 |
|---|---|---|
| 첫 번째 | `(int, int)` | 사용자가 입력한 `(MLB ID, 연도)` |
| 두 번째 | `(int, int)` | `find_nearest_pitcher` 가 돌려준 `(MLB ID, 연도)` |

**반환:** `dict` — 응답의 `"llm"` 필드에 그대로 들어갑니다.

> 현재 `main.py` 에서는 LLM 호출(`call_llm_client`)이 주석 처리되어 있어 `"llm"` 에 빈 dict(`{}`)가 들어갑니다. `llm_client.py` 가 완성되면 `compare_pitcher()` 의 주석을 풀어 주세요.

---

## 🔗 `main.py` 에서의 처리

```
GET /{player_id}/{year}
  1. pitcher_clustered.json 에 (player_id, year) 가 있는지 확인        → 없으면 404
  2. nearest = find_nearest_pitcher(player_id, year, top_n)            # top_n 이 rank 로 전달됨
  3. nearest 가 None 이면 LLM 을 부르지 않고 "matched": false 응답
  4. answer  = llm_client((player_id, year), nearest)
  5. {"matched": true, "message": null, "query": {...}, "nearest": {...}, "llm": answer} 응답
```

매칭되는 선수가 없을 때의 응답 (`200`):

```json
{
  "matched": false,
  "message": "조건에 맞는 유사 투수를 찾지 못했습니다.",
  "query":   { "player_id": 660271, "year": 2023 },
  "nearest": null,
  "llm":     null
}
```

| 상황 | 응답 |
|---|---|
| `find_nearest_pitcher` 가 `None` 또는 빈 리스트를 반환 | `200` + `"matched": false` |
| `find_nearest_pitcher` 가 예외를 던지거나 `(ID, 연도)` 형태가 아닌 값을 반환 | `500` |
| `llm_client.py` 가 없거나 import 중 오류 | `503` |
| `llm_client` 가 예외를 던지거나 `dict` 가 아닌 값을 반환 | `502` |

* 반환값에 numpy 정수가 섞여 있어도 `main.py` 가 파이썬 `int` 로 바꿉니다.
* 두 함수는 FastAPI 가 별도 스레드에서 실행하므로, 일반 동기 함수(`def`)로 작성하면 됩니다.
* 함수 이름·인자·반환 형태가 바뀌면 `main.py` 의 `call_find_nearest_pitcher()`, `call_llm_client()` 도 함께 고쳐야 합니다.

## ⚠️ 작업 규칙

* **API 키 관리:** LLM 호출에 필요한 키 등은 코드에 직접 쓰지 말고 `.env` 에 두세요. 필요한 변수 이름은 `.env.example` 에 추가합니다.
* **import 경로:** `main.py` 는 `from src.utils.find_nearest_pitcher import ...`, `from src.utils.llm_client import llm_client` 로 불러옵니다. 파일명과 함수명을 이대로 유지해 주세요.
* **무거운 작업은 요청마다 하지 않기:** 원본 CSV 읽기처럼 오래 걸리는 작업은 서버 시작 때 한 번만 하고, 요청 처리 함수에서는 미리 만든 파일·메모리 캐시를 사용합니다.
