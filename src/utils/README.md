# 🛠️ Utils (유사 투수 탐색 · LLM 클라이언트)

백엔드 API(`main.py` 의 `GET /{player_id}/{year}`)가 호출하는 모듈을 두는 폴더입니다. 🚧 **담당 팀원이 작업 중입니다.**

## 📄 모듈 인터페이스

`main.py` 는 아래 이름과 형태를 기준으로 두 함수를 호출합니다. 이름·인자·반환 형태가 바뀌면 `main.py` 의 `call_find_nearest_pitcher()`, `call_llm_client()` 도 함께 고쳐야 합니다.

### `find_nearest_pitcher.py` — `find_nearest_pitcher(player_id, year, top_n)`

입력한 투수-시즌과 가장 비슷한 투수-시즌을 찾습니다.

| 인자 | 타입 | 설명 |
|---|---|---|
| `player_id` | `int` | MLB(MLBAM) 선수 ID |
| `year` | `int` | 시즌 연도 |
| `top_n` | `int` | `main.py --top-n` 으로 전달 (기본값 `1`) |

**반환:** `(MLB ID, 연도)` 튜플 하나.

### `llm_client.py` — `llm_client(query, nearest)`

두 투수-시즌을 받아 LLM 답변을 돌려줍니다.

| 인자 | 타입 | 설명 |
|---|---|---|
| `query` | `(int, int)` | 사용자가 입력한 `(MLB ID, 연도)` |
| `nearest` | `(int, int)` | `find_nearest_pitcher` 가 돌려준 `(MLB ID, 연도)` |

**반환:** `dict` — `main.py` 가 응답의 `"llm"` 필드에 그대로 넣어 프론트엔드로 보냅니다.

## 🔗 `main.py` 에서의 처리

```
GET /{player_id}/{year}
  1. pitcher_clustered.json 에 (player_id, year) 가 있는지 확인     → 없으면 404
  2. nearest = find_nearest_pitcher(player_id, year, top_n)
  3. answer  = llm_client((player_id, year), nearest)
  4. {"query": {...}, "nearest": {...}, "llm": answer} 응답
```

| 상황 | 응답 코드 |
|---|---|
| 모듈 파일이 없거나 import 중 오류 | `503` |
| `find_nearest_pitcher` 가 예외를 던지거나 `(ID, 연도)` 형태가 아닌 값을 반환 | `500` |
| `find_nearest_pitcher` 가 `None` 또는 빈 리스트를 반환 | `404` |
| `llm_client` 가 예외를 던지거나 `dict` 가 아닌 값을 반환 | `502` |

* 반환값에 numpy 정수가 섞여 있어도 `main.py` 가 파이썬 `int` 로 바꿉니다.
* 두 함수는 FastAPI 가 별도 스레드에서 실행하므로, 일반 동기 함수(`def`)로 작성하면 됩니다.

## ⚠️ 작업 규칙

* **API 키 관리:** LLM 호출에 필요한 키 등은 코드에 직접 쓰지 말고 `.env` 에 두세요. 필요한 변수 이름은 `.env.example` 에 추가합니다.
* **import 경로:** `main.py` 는 `from src.utils.find_nearest_pitcher import find_nearest_pitcher`, `from src.utils.llm_client import llm_client` 로 불러옵니다. 파일명과 함수명을 이대로 유지해 주세요.
