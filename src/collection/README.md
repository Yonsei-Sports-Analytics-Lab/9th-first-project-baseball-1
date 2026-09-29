# 📥 Collection (데이터 수집) — 예정

원본 데이터를 자동으로 수집하는 스크립트를 두는 폴더입니다. **현재는 비어 있습니다.**

지금은 Baseball Savant 에서 Statcast 투구 데이터를 월별 CSV 로 직접 내려받아 구글 드라이브로 공유하고 있습니다. 받은 파일을 두는 위치와 파일명 규칙은 [`data/raw/README.md`](../../data/raw/README.md) 를 참고하세요.

## ⚠️ 작성 규칙 (수집 스크립트를 추가할 때)

* **파라미터화:** 시작·종료 날짜나 연도를 인자로 받도록 작성합니다.
* **저장 위치와 파일명:** 전처리가 바로 읽을 수 있도록 `data/raw/{연도}/statcast_{연도}-{MM}.csv` 로 저장합니다.
* **컬럼 유지:** `extract_fastball.py` 가 요구하는 필수 컬럼과 `pitcher`, `player_name`, `arm_angle` 이 포함되어야 합니다.
