# 🧠 Models — 예정

별도의 학습 모델(예측·분류 모델 등)을 정의하고 학습·평가하는 코드를 두는 폴더입니다. **현재는 비어 있습니다.**

현재 프로젝트의 모델인 **투구 클러스터링 GMM** 은 전처리 파이프라인의 일부로 `src/preprocessing/` 에 있습니다.

* 적합: `src/preprocessing/fit_pitch_gmm.py`
* 평가: `src/preprocessing/evaluate_pitch_gmm.py`
* 저장 위치: `data/processed/pitch_type_gmm_k{K}.joblib`

## ⚠️ 작성 규칙 (모델을 추가할 때)

* **구조와 실행 분리:** 모델 정의와 학습·평가 스크립트를 분리합니다.
* **하이퍼파라미터 관리:** 코드 중간에 하드코딩하지 말고 파일 상단 상수나 CLI 인자로 받습니다.
* **가중치 파일:** 학습된 모델 파일은 용량이 클 수 있으므로 `data/processed/` 등 `.gitignore` 로 제외된 위치에 저장합니다.
