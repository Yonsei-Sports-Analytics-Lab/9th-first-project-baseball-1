# 🎨 Visualization (시각화 및 대시보드 연동 모듈)

이 폴더는 탐색적 데이터 분석(EDA) 결과나 모델의 예측 결과를 시각적으로 표현하고, 프론트엔드 웹 화면이나 BI 툴과 연동하기 위한 코드들을 보관하는 곳입니다.

## ⚠️ 작업 규칙

1. **출력 결과물(Artifacts) 관리:** 
   코드를 통해 생성된 대용량 이미지 파일(`.png`, `.svg` 등)은 저장소 용량을 크게 차지할 수 있으므로 가급적 GitHub에 직접 커밋하지 않도록 주의해 주세요.
2. **독립성 유지:** 
   시각화 함수는 데이터 전처리나 모델 학습 코드와 강하게 결합되지 않도록 작성해야 합니다. 정제가 완료된 데이터프레임이나 예측 배열(Array)을 입력받아 그림만 그려주는 독립적인 형태로 설계하는 것이 좋습니다.

## 📄 파일 구성 예시

* `pitch_trajectory.py`: Statcast 운동 파라미터와 투구 무브먼트(`pfx_x`, `pfx_z`)를 활용해 프론트엔드용 3D 궤적 좌표를 복원하는 모듈
* `dashboard_formatter.py`: `data/processed/data_*.csv`를 읽고 투수별 개별 궤적 JSON을 생성하는 모듈
* `pitch_3d/`: 생성된 JSON을 렌더링하는 React Three Fiber 뷰어
* `tableau_export.py`: Tableau 시각화를 위해 필요한 요약 통계량(예: 투수별 구종 구사율 등)을 집계하여 추출하는 스크립트

## 투구 궤적 복원

`pitch_trajectory.py`는 실제 투구 행에 `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az`가
있으면 Baseball Savant CSV의 50 ft 기준 운동식을 우선 사용합니다. 이 값이 없는
구종 평균 데이터에서는 `release_speed`, 릴리스 위치, `plate_x`, `plate_z`,
`pfx_x`, `pfx_z`로 보조 궤적을 만듭니다. Savant CSV의 `pfx_*` 단위는 ft입니다.

```python
from src.visualization.pitch_trajectory import reconstruct_pitch_trajectory

trajectory = reconstruct_pitch_trajectory(
    statcast_row,
    samples=61,
    coordinate_system="threejs",
)

# React/Three.js API 응답에는 trajectory["points"]를 전달합니다.
```

## CSV에서 뷰어 데이터 생성

`data/processed`에 `data_*.csv`를 둔 뒤 아래 명령을 실행합니다.

```bash
python3 main.py --list-pitchers
python3 main.py --pitcher "Shohei Ohtani"
```

한 투수만 들어 있는 CSV에서는 `--pitcher`를 생략할 수 있습니다. 결과는 기본적으로
`pitch_3d/public/pitch-data.json`에 생성되며, 실제 React 앱은 이 파일을 fetch한 뒤
`<Pitch3D data={data} />`로 전달합니다. 자세한 필수 열과 사용법은
`pitch_3d/README.md`를 참고하세요.
