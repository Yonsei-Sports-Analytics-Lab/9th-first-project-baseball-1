# 📂 Raw Data (원본 데이터)

Baseball Savant 에서 내려받은 **Statcast 투구 단위(pitch-by-pitch) 월별 CSV** 와 **투수-시즌별 FIP 파일** 을 보관하는 폴더입니다.
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
├── 2025/
└── fip_2021_2025.csv          # 투수-시즌별 FIP (연도 폴더 밖, data/raw 바로 아래)
```

* 연도 폴더 이름은 **4자리 숫자**(`2021`)여야 합니다.
* 월별 파일명은 **`statcast_{연도}-{MM}.csv`** 여야 합니다. 이 규칙에 맞지 않는 파일(엑셀 임시 파일 `~$...`, 폴더 연도와 파일명 연도가 다른 파일 등)은 전처리와 프로필 생성에서 모두 건너뜁니다.
* 연도 폴더를 새로 추가하면, 다음 파이프라인 실행 때 **그 연도만** 새로 전처리됩니다.

## 📄 파일별 사용처

| 파일 | 읽는 코드 | 용도 |
|---|---|---|
| `{연도}/statcast_{연도}-{MM}.csv` | `src/preprocessing/extract_fastball.py` | 패스트볼(FF/SI/FC)만 추출해 전처리 파이프라인 시작 |
| `{연도}/statcast_{연도}-{MM}.csv` | `src/utils/find_nearest_pitcher.py` (`build_profile`) | **모든 구종** 투구로 투수-시즌별 투구 폼(릴리스 좌우·높이, 익스텐션, 팔 각도) 평균 계산 |
| `fip_2021_2025.csv` | `src/utils/find_nearest_pitcher.py` (`build_profile`) | 유사 투수 조건(더 낮은 FIP)과 최소 이닝 조건에 사용 |

### 월별 Statcast 파일의 필수 컬럼

* **전처리** (`extract_fastball.py`, 없으면 오류, 값이 비어 있는 행은 제거):
  `pitch_type`, `pfx_x`, `pfx_z`, `release_pos_x`, `release_pos_y`, `release_pos_z`, `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az`, `release_speed`, `p_throws`, `release_extension`, `game_year`
  이후 단계에서 `pitcher`(MLB ID), `player_name`, `arm_angle` 도 사용합니다.
* **투수 프로필** (`build_profile`):
  `pitcher`, `player_name`, `game_year`, `p_throws`, `release_pos_x`, `release_pos_z`, `release_extension`, `arm_angle`

각 컬럼의 의미는 루트의 [`STATCAST_2021_03_변수설명서.md`](../../STATCAST_2021_03_변수설명서.md) 를 참고하세요.

### `fip_2021_2025.csv` 컬럼

| 컬럼 | 설명 |
|---|---|
| `player_id` | MLB(MLBAM) 선수 ID — Statcast `pitcher` 와 같은 값 |
| `game_year` | 시즌 연도 |
| `player_name_fip` | 선수 이름 (확인용) |
| `outs`, `hr`, `bb`, `hbp`, `so`, `er` | 아웃 카운트, 피홈런, 볼넷, 사구, 삼진, 자책점 |
| `IP` | 이닝 |
| `FIP` | 수비 무관 평균자책점 |

`build_profile` 은 이 중 `player_id`, `game_year`, `FIP`, `IP` 만 사용합니다.

## 📥 데이터 받기

전체 원본은 용량이 커서 GitHub 에 올리지 않습니다. `.gitignore` 가 `data/raw/` 아래를 `README.md` 등 일부를 빼고 모두 제외하므로 **`fip_2021_2025.csv` 도 커밋되지 않습니다.** 작업 전에 아래 구글 드라이브에서 받아 위 구조대로 넣어 주세요.

* **Statcast 2021~2025 월별 투구 데이터:** [구글 드라이브](https://drive.google.com/drive/folders/1uxGd0kggrNSZbuXRMXHij4qSTAYBeocL?usp=sharing)
* **`fip_2021_2025.csv`:** 같은 드라이브로 공유합니다. 드라이브에 없으면 파일을 만든 팀원에게 받아 `data/raw/` 바로 아래에 넣어 주세요.
