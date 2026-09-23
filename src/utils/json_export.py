"""군집 결과를 팀 공용 JSON 형식으로 저장한다.

형식 (data_description.json 견본과 동일):

{
  "Shohei Ohtani": {
    "2024": { "average_velocity": 96.8, "cluster": 1 }
  }
}
"""
import json
from pathlib import Path

from src.utils.config import VELOCITY_COLUMN


def flip_name(name):
    """Statcast의 'Ohtani, Shohei' → 견본 형식인 'Shohei Ohtani'."""
    if not isinstance(name, str):
        return name
    if "," not in name:
        return name.strip()
    last, first = name.split(",", 1)
    return f"{first.strip()} {last.strip()}".strip()


def build_pitcher_json(points, cluster_col="cluster", velocity_col=VELOCITY_COLUMN):
    """투수-시즌 DataFrame → {선수: {시즌: {average_velocity, cluster}}} 딕셔너리.

    한 투수의 한 시즌은 한 줄이어야 한다 (pick_primary_pitch 결과를 넣을 것).
    이름+시즌이 겹치면(동명이인) 투구 수가 많은 쪽만 남기고 개수를 알린다.
    """
    required = {"player_name", "game_year", cluster_col}
    missing = required - set(points.columns)
    if missing:
        raise KeyError(f"필요한 칼럼이 없습니다: {sorted(missing)}")

    rows = points.copy()
    rows["display"] = rows["player_name"].map(flip_name)

    sort_col = "n_pitches" if "n_pitches" in rows.columns else cluster_col
    rows = rows.sort_values(sort_col, ascending=False)
    before = len(rows)
    rows = rows.drop_duplicates(subset=["display", "game_year"], keep="first")
    if len(rows) < before:
        print(f"⚠️ 이름+시즌이 겹쳐 {before - len(rows)}개를 제외했습니다 (동명이인 가능).")

    has_velocity = velocity_col in rows.columns
    result = {}
    for row in rows.sort_values(["display", "game_year"]).itertuples(index=False):
        record = {}
        if has_velocity:
            velocity = getattr(row, velocity_col)
            record["average_velocity"] = None if velocity != velocity else round(float(velocity), 1)
        record["cluster"] = int(getattr(row, cluster_col))
        season = str(int(getattr(row, "game_year")))
        result.setdefault(getattr(row, "display"), {})[season] = record
    return result


def save_pitcher_json(points, path, cluster_col="cluster", velocity_col=VELOCITY_COLUMN):
    """build_pitcher_json 결과를 파일로 저장하고 딕셔너리를 돌려준다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build_pitcher_json(points, cluster_col=cluster_col, velocity_col=velocity_col)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    seasons = sum(len(v) for v in data.values())
    print(f"저장 완료: {path.name} (투수 {len(data):,}명 / 투수-시즌 {seasons:,}개)")
    return data
