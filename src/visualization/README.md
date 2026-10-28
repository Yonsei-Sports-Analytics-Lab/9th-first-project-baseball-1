# 🎨 Visualization (시각화 및 3D 투구 뷰어)

분석 결과를 시각화하고 개별 투구 궤적을 3D로 렌더링하는 코드를 두는 폴더입니다.
기존 무브먼트 산점도, 클러스터별 분포, BIC 곡선 등은 `notebooks/`의
`DBSCAN_EDA.ipynb`, `GMM_pitch_repertoire.ipynb`에 있습니다.

## ⚠️ 작성 규칙

* **독립성 유지:** 전처리·모델 코드와 강하게 묶지 말고, 정제된 DataFrame이나 `pitcher_clustered.json` 같은 산출물을 입력받아 시각화합니다.
* **출력물 관리:** 생성한 이미지(`.png`, `.svg` 등)와 대용량 JSON은 가급적 커밋하지 않습니다.
* **축 방향 통일:** 무브먼트 평면은 x축 `hb_ft`(암사이드 +), y축 `ivb_ft`로 그려 노트북과 일관되게 유지합니다.

## 📄 파일 구성

* `pitch_trajectory.py`: Statcast 운동 파라미터와 투구 무브먼트(`pfx_x`, `pfx_z`)를 활용해 3D 궤적 좌표를 복원하는 모듈
* `dashboard_formatter.py`: `data/processed/data_*.csv`를 읽고 투수별 개별 궤적 JSON을 생성하는 모듈
* `pitch_3d/`: 생성된 JSON을 렌더링하는 React Three Fiber 뷰어

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
```

## CSV에서 뷰어 데이터 생성

`data/processed`에 `data_*.csv`를 둔 뒤 변환 모듈을 실행합니다.

```bash
python -m src.visualization.dashboard_formatter --list-pitchers
python -m src.visualization.dashboard_formatter --pitcher "Shohei Ohtani"
```

한 투수만 들어 있는 CSV에서는 `--pitcher`를 생략할 수 있습니다. 결과는 기본적으로
`pitch_3d/public/pitch-data.json`에 생성되며, React 앱은 이 파일을 fetch한 뒤
`<Pitch3D data={data} />`로 전달합니다. 자세한 필수 열과 사용법은
[`pitch_3d/README.md`](./pitch_3d/README.md)를 참고하세요.
