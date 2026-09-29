# 📂 Raw Data (원본 데이터)

Baseball Savant 에서 내려받은 **Statcast 투구 단위(pitch-by-pitch) 월별 CSV** 를 보관하는 폴더입니다.
이 폴더의 파일은 **어떤 경우에도 직접 수정하지 않습니다.** 정제·변환 결과는 모두 `data/processed/` 에 저장됩니다.

## 📁 폴더 구조와 파일명 규칙

```
data/raw/
├── 2021/
│   ├── statcast_2021-03.csv
│   ├── statcast_2021-04.csv
│   └── ...
├── 2022/
├── 2023/
├── 2024/
└── 2025/
```

* 연도 폴더 이름은 **4자리 숫자**(`2021`)여야 합니다.
* 파일명은 **`statcast_{연도}-{MM}.csv`** 여야 합니다. 이 규칙에 맞지 않는 파일(엑셀 임시 파일 `~$...`, 폴더 연도와 파일명 연도가 다른 파일 등)은 전처리에서 경고를 남기고 건너뜁니다.
* 연도 폴더를 새로 추가하면, 다음 파이프라인 실행 때 **그 연도만** 새로 전처리됩니다.

## 📋 전처리에 반드시 필요한 컬럼

`src/preprocessing/extract_fastball.py` 는 아래 컬럼이 없으면 오류를 냅니다(값이 비어 있는 행은 제거).

`pitch_type`, `pfx_x`, `pfx_z`, `release_pos_x`, `release_pos_y`, `release_pos_z`, `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az`, `release_speed`, `p_throws`, `release_extension`, `game_year`

이후 단계에서는 `pitcher`(MLB ID), `player_name`, `arm_angle` 도 사용합니다. 각 컬럼의 의미는 루트의 [`STATCAST_2021_03_변수설명서.md`](../../STATCAST_2021_03_변수설명서.md) 를 참고하세요.

## 📥 데이터 받기

전체 원본은 용량이 커서 GitHub 에 올리지 않습니다(`.gitignore` 로 제외). 작업 전에 아래 구글 드라이브에서 받아 위 구조대로 넣어 주세요.

* **Statcast 2021~2025 월별 투구 데이터:** [구글 드라이브](https://drive.google.com/drive/folders/1uxGd0kggrNSZbuXRMXHij4qSTAYBeocL?usp=sharing)
