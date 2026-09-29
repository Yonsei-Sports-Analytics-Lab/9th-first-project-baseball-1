# 💻 Source Code (`src/`)

프로젝트의 핵심 로직을 담당하는 파이썬 모듈입니다. 전체 실행은 루트의 `main.py` 가 담당합니다.

## 📁 디렉토리 구조 및 역할

| 폴더 | 상태 | 역할 |
|---|---|---|
| [`preprocessing/`](preprocessing/README.md) | ✅ 구현 | 원본 → 패스트볼 추출 → 체공시간 보정 무브먼트 → GMM 적합 → 투수-시즌 클러스터 JSON. 파이프라인과 GMM 평가 포함 |
| [`utils/`](utils/README.md) | 🚧 작업 중 | 유사 투수 탐색(`find_nearest_pitcher`), LLM 호출(`llm_client`) |
| [`collection/`](collection/README.md) | 예정 | 원본 데이터 수집 자동화 (현재는 Baseball Savant 에서 직접 내려받음) |
| [`models/`](models/README.md) | 예정 | 별도 학습 모델 (현재 GMM 은 `preprocessing/` 에 있음) |
| [`visualization/`](visualization/README.md) | 예정 | 클러스터·투수 비교 시각화 |

## 🔄 데이터 흐름

```
data/raw  ──preprocessing──▶  data/processed/pitcher_clustered.json
                                         │
main.py  GET /{player_id}/{year}  ◀──────┘
   ├─ utils.find_nearest_pitcher  →  가장 비슷한 (MLB ID, 연도)
   └─ utils.llm_client            →  두 투수-시즌 LLM 분석 (dict)
```

## ⚠️ 작성 규칙

* **재사용 가능한 함수로 작성:** 스크립트로 실행하는 모듈도 핵심 로직은 `run()` 같은 함수로 두고, `argparse` 는 `main()` 과 `if __name__ == "__main__":` 안에서만 씁니다. 그래야 다른 모듈과 노트북에서 import 해서 쓸 수 있습니다.
* **패키지 경로로 import:** 모듈끼리는 `from src.preprocessing.xxx import ...` 처럼 프로젝트 루트 기준 경로로 불러옵니다. 루트에서 실행하는 `main.py` 는 그대로 동작하고, 노트북은 루트를 `sys.path` 에 추가해야 합니다.
* **경로 하드코딩 금지:** 데이터 경로는 `Path(__file__)` 기준으로 프로젝트 루트를 구해 만듭니다.

> 각 하위 폴더의 `README.md` 에 모듈별 사용법과 규칙이 있습니다.
