# 📓 Notebooks (EDA 및 실험)

Jupyter Notebook 으로 **데이터 탐색(EDA), 군집 알고리즘 실험, 시각화 프로토타입** 을 진행하는 폴더입니다.
노트북은 **실험 기록용** 이고, 검증된 로직은 `src/` 의 파이썬 모듈로 옮깁니다.

## 📄 노트북 목록

| 노트북 | 내용 | 결론 / 현재 코드와의 관계 |
|---|---|---|
| `example.ipynb` | 노트북 작성 템플릿 (경로 설정, autoreload) | 새 노트북을 만들 때 복사해서 사용 |
| `DBSCAN_EDA.ipynb` | `ivb_ft` × `hb_ft` 평면에 DBSCAN 적용 (eps 탐색, 실루엣 등 평가) | 패스트볼 무브먼트는 밀도가 끊기는 곳이 없는 연속체라 DBSCAN 으로는 나뉘지 않음 → GMM 으로 전환 |
| `GMM_pitch_repertoire.ipynb` | `ivb_ft`, `hb_ft`, `arm_angle` 로 GMM 적합, BIC 로 K 탐색, 투수 레퍼토리 군집화 실험 | K 선택 근거를 여기서 확인. 투구 단위 GMM 부분은 `src/preprocessing/` 로 옮겨짐 |

> **현재 파이프라인과의 차이:** `GMM_pitch_repertoire.ipynb` 는 2021~2023년으로만 GMM 을 적합하고, 투수-시즌 확률 벡터를 KMeans 로 한 번 더 군집화합니다. 지금 `src/preprocessing/` 파이프라인은 **모든 연도로 GMM 을 적합** 하고, 투수-시즌마다 **가장 많이 속한 GMM 클러스터(최빈값)** 를 기록합니다. 두 번째 KMeans 단계는 없습니다.

## ⚠️ 작업 규칙

1. **코드 모듈화:** 노트북에서 검증한 전처리·모델 로직은 `src/` 하위 `.py` 파일로 옮깁니다.
2. **출력 결과 정리:** 큰 데이터프레임이나 그래프 출력이 남은 채로 커밋하면 파일이 커지고 PR 충돌이 잦아집니다. 커밋 전에 **Clear All Outputs** 를 실행해 주세요.
3. **절대 경로 사용 금지:** `C:/Users/...` 같은 개인 경로 대신 프로젝트 루트 기준 상대 경로(`../data/processed/...`)를 사용합니다.

## 📝 파일 네이밍

`[순서번호]_[작업자이니셜]_[작업내용].ipynb` 형식을 권장합니다. (예: `03_BG_gmm_k_selection.ipynb`)

## 💡 `src/` 모듈 불러오기

노트북 최상단 셀에 프로젝트 루트를 경로로 추가하면 `src.` 로 시작하는 import 를 쓸 수 있습니다.

```python
import sys, os
sys.path.append(os.path.abspath('..'))   # notebooks/ 의 상위 = 프로젝트 루트

from src.preprocessing.load_movement_data import find_movement_files, load_pitch_data
from src.preprocessing.fit_pitch_gmm import load_model
from src.preprocessing.cluster_pitcher_repertoire import run as cluster_run

model = load_model('../data/processed/pitch_type_gmm_k6.joblib')
seasons, model, pitches = cluster_run(
    model=model, processed_dir='../data/processed', save_json=False,   # 파일 저장 없이 DataFrame 으로 받기
)
```

CLI 스크립트의 `main()` 을 노트북에서 부를 때는 반드시 인자 리스트를 넘기세요 (`main(["--k", "6", "--dry-run"])`). 빈 괄호로 부르면 Jupyter 의 실행 인자를 argparse 가 읽어 오류가 납니다.
