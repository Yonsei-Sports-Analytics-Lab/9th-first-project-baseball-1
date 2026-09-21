"""프로젝트 공통 경로와 상수.

경로는 이 파일 위치를 기준으로 계산하므로, 누구 컴퓨터에서 어디서 실행하든
프로젝트 root 아래 data/ 폴더를 가리킨다. (절대경로 하드코딩 없음)
"""
from pathlib import Path

# 프로젝트 root = src/utils/config.py 기준 두 단계 위
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# 분석 대상 패스트볼
FASTBALLS = ["FF", "SI", "FC"]

# 원본 CSV에서 읽을 칼럼 (메모리 절약)
NEEDED_COLUMNS = [
    "pitch_type", "game_year", "game_type", "description",
    "pitcher", "player_name", "p_throws",
    "pfx_x", "pfx_z", "release_pos_y", "vy0", "ay", "arm_angle",
]
NUMERIC_COLUMNS = ["pfx_x", "pfx_z", "release_pos_y", "vy0", "ay", "arm_angle", "game_year"]

# 체공시간 계산 상수 (체공시간_보정_무브먼트_계산_가이드.md)
PLATE_Y_FT = 17.0 / 12.0      # 홈플레이트 앞면 y좌표
REFERENCE_Y_FT = 50.0         # Statcast 궤적 계수 기준 y좌표
MIN_FLIGHT_TIME_S = 0.25
MAX_FLIGHT_TIME_S = 0.60

# 군집분석 변수
CLUSTER_FEATURES = ["ivb_ft", "hb_ft", "arm_angle"]
