# 📂 Processed Data (전처리 완료 데이터)

이 폴더는 `data/raw/`에 있는 원본 데이터를 바탕으로 정제, 변환, 스케일링 등의 전처리 작업이 완료된 **모델 학습용 데이터**를 보관하는 곳입니다.

## ⚠️ 작업 규칙 및 주의사항

1. **직접 수정 금지:** 
   이 폴더에 있는 CSV 파일이나 넘파이 배열(`.npy`) 등은 엑셀 등으로 직접 열어서 값을 수정하면 안 됩니다. 모든 변경 사항은 코드를 통해 추적 가능해야 합니다.
2. **재현 가능성 (Reproducibility):** 
   이 폴더 안의 데이터가 실수로 삭제되더라도, `src/preprocessing/` 폴더에 있는 파이썬 스크립트를 실행하면 **언제든 똑같이 다시 생성될 수 있어야 합니다.**
3. **용량 주의:** 
   전처리가 끝난 전체 데이터셋(예: 5만 건 이상의 피처 엔지니어링 결과) 역시 용량이 클 수 있으므로 GitHub에 직접 커밋되지 않도록 `.gitignore` 규칙을 따릅니다.

## 📝 파일 네이밍 컨벤션 (Naming Convention)

생성된 데이터 파일은 어떤 과정을 거쳤는지 쉽게 알 수 있도록 명확하게 이름을 짓습니다.

* `[데이터성격]_[처리내용]_[버전/날짜].csv`
* **예시:**
  * `pitch_data_cleaned_v1.csv` (결측치 제거 완료)
  * `pitch_features_scaled_202603.csv` (스케일링 및 파생 변수 추가 완료)
  * `X_train_lstm.npy`, `y_train_lstm.npy` (LSTM 모델 입력용으로 형태 변환 완료)

3D 투구 뷰어가 읽는 파일은 `data_[설명].csv` 형식으로 저장합니다. 예를 들어
`data_ohtani_2024.csv`, `data_verlander.csv`는 자동 탐색 대상입니다. 여러 파일을
함께 둘 수 있고, CSV에 여러 투수가 있으면 실행 시 투수 이름을 선택합니다.

## 🔄 전처리 실행 방법

새로운 파생 변수를 추가하거나 정제 로직을 바꾼 경우, 아래와 같이 전처리 파이프라인 스크립트를 실행하여 이 폴더의 데이터를 갱신합니다.
```bash
# 예시 스크립트 실행
python3 src/preprocessing/data_pipeline.py
```

## 3D 투구 시각화 데이터 생성

```bash
python3 main.py --list-pitchers
python3 main.py --pitcher "Shohei Ohtani"
```

개별 투구 CSV에는 Statcast의 `pitch_type`, `release_speed`, `plate_x`, `plate_z`,
`release_pos_y`, `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az` 열 사용을 권장합니다.
운동 파라미터가 없으면 릴리스 위치와 `pfx_x`, `pfx_z`를 사용하는 보조 모델로
복원합니다. 전체 데이터 계약은 `src/visualization/pitch_3d/README.md`에 있습니다.

### 📥 데이터 다운로드 링크
* **2024시즌 전체 투구 데이터 (Statcast):** [구글 드라이브 링크(클릭)](#)
