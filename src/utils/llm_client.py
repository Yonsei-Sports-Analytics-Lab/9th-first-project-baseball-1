"""LLM 변화구 추천 모듈 (파이프라인 6번 단계).

입력 투수와 5번 단계가 매칭한 유사 투수의 MLB ID·연도를 받아, 두 투수의 Statcast 구종 데이터를
정리해 LLM(Gemini 또는 OpenAI GPT)에 전달하고, LLM에 넣은 데이터(스탯)와 답변을 함께 dict로 돌려준다.

사용법 (main.py 등):
    from src.utils.llm_client import llm_client

    result = llm_client(
        input_mlbid=660271, input_year=2023,       # 추천받을 투수 (Statcast 'pitcher' 값 = MLB ID)
        similar_mlbid=434378, similar_year=2024,   # 5번 단계가 매칭한 유사 투수
    )
    result["payload"]["input_pitcher"]["arsenal"]   # LLM에 넣은 입력 투수 구종별 스탯
    result["response"]["recommendations"]           # LLM 답변 — 모두 dict (JSON 문자열 아님)

준비:
    1) 레포 루트 data/raw/ 아래에 Statcast pitch-level CSV
       (첫 호출 때 구종 집계 캐시 data/processed/interim/pitch_arsenal.pkl 생성, 이후 재사용)
    2) 레포 루트 .env 에 GEMINI_API_KEY=... (무료) 또는 OPENAI_API_KEY=...  (.env.example 참고)

반환 dict:
    {
      "model": 실제로 답한 모델 이름,
      "created_at": 생성 시각,
      "payload": LLM에 넣은 데이터 {
          search_context,
          input_pitcher   {pitcher_id, player_name, season, throws, primary_fastball{…}, arsenal[구종별 스탯]},
          similar_pitcher {…같은 구조},
          transfer_targets[{pitch_type, gap_vs_fb, target_shape, …}]   # 코드가 계산한 목표 shape
      },
      "response": LLM 답변 {
          summary, fastball_comparison{similarities, differences},
          recommendations[{rank, pitch_type, pitch_name, action, target_shape, gap_vs_fastball,
                           rationale, usage_plan, confidence, caveats}],
          failure_cases[{pitcher, pitch_type, lesson}], not_recommended[{pitch_type, reason}],
          data_limitations[]
      },
      "validation_warnings": 자동 검증 경고 리스트 (비어 있으면 통과)
    }

부호 규칙: HB는 암사이드(투수 팔 쪽) +, RV/100은 투수 기준 + = 좋음.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

__all__ = ["llm_client"]


# ------------------------------------------------------------
# 경로 (레포 루트 기준 상대경로 — 절대경로 사용 안 함)
# ------------------------------------------------------------
def _find_repo_root() -> Path:
    """이 파일(src/utils/)에서 위로 올라가며 .git 또는 data 폴더가 있는 곳을 레포 루트로 본다."""
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "data").is_dir():
            return candidate
    return Path.cwd().resolve()


ROOT = _find_repo_root()
RAW_DIR = ROOT / "data" / "raw"
INTERIM_DIR = ROOT / "data" / "processed" / "interim"
ARSENAL_PKL = INTERIM_DIR / "pitch_arsenal.pkl"


def rel(p: Path) -> str:
    """출력용 상대경로 (공개 레포라 절대경로/사용자명 노출 방지)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).name




# ============================================================
# 1. 구종 집계 (data/raw Statcast → 투수-시즌-구종 요약표)
# ============================================================
TARGET_YEARS = [2021, 2022, 2023, 2024, 2025]
FASTBALL_TYPES = ["FF", "SI", "FC"]          # 팀 공통: 주 패스트볼 후보
EXCLUDE_PITCH_TYPES = {"PO", "FA", "EP", "CS", "KN", "SC", "IN", "UN", "AB"}  # 피치아웃/이퓨스 등
MIN_PITCHES_TO_LIST = 20                      # 이보다 적게 던진 구종은 프롬프트에서 제외
SMALL_SAMPLE_PITCHES = 100                    # 이보다 적으면 '표본 작음' 표시
SMALL_SAMPLE_BBE = 30                         # 인플레이 타구가 이보다 적으면 GB%/xwOBAcon 불안정

USECOLS = {
    "pitcher", "player_name", "game_year", "game_type", "pitch_type", "pitch_name",
    "description", "zone", "stand", "p_throws",
    "release_speed", "pfx_x", "pfx_z", "release_spin_rate",
    "release_extension", "arm_angle", "release_pos_x", "release_pos_z",
    "delta_run_exp",
    "bb_type", "estimated_woba_using_speedangle",   # GB%, xwOBAcon용
}

SWING_DESC = {
    "swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
    "hit_into_play", "foul_bunt", "missed_bunt", "bunt_foul_tip",
}
WHIFF_DESC = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}
CALLED_STRIKE_DESC = {"called_strike"}


# ------------------------------------------------------------
# raw 로드
# ------------------------------------------------------------
# data/raw/{연도}/statcast_{연도}-{MM}.csv 만 읽는다 (fip_*.csv, 엑셀 임시파일 "~$..." 등 제외)
RAW_FILE_PATTERN = re.compile(r"^statcast_\d{4}-\d{2}\.csv$")


def load_raw_pitches(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    files = sorted(f for f in raw_dir.rglob("statcast_*.csv") if RAW_FILE_PATTERN.match(f.name))
    if not files:
        raise FileNotFoundError(
            f"{rel(raw_dir)} 안에 statcast_{{연도}}-{{MM}}.csv 가 없습니다. "
            "Baseball Savant pitch-level CSV를 넣어주세요."
        )
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, low_memory=False, usecols=lambda c: c in USECOLS))
        except Exception as e:  # 깨진 파일은 건너뜀
            print(f"[arsenal] 읽기 실패, 건너뜀: {rel(f)} ({e})")
    data = pd.concat(frames, ignore_index=True)

    num_cols = ["game_year", "zone", "release_speed", "pfx_x", "pfx_z", "release_spin_rate",
                "release_extension", "arm_angle", "release_pos_x", "release_pos_z", "delta_run_exp",
                "estimated_woba_using_speedangle"]
    for c in num_cols:
        if c in data.columns:
            data[c] = pd.to_numeric(data[c], errors="coerce")

    mask = (
        (data["game_type"] == "R")
        & data["game_year"].isin(TARGET_YEARS)
        & data["p_throws"].isin(["R", "L"])
        & data["pitch_type"].notna()
        & ~data["pitch_type"].isin(EXCLUDE_PITCH_TYPES)
        & (data["description"] != "pitchout")
    )
    data = data.loc[mask].copy()
    data["game_year"] = data["game_year"].astype(int)
    print(f"[arsenal] raw 파일 {len(frames)}개, 정규시즌 투구 {len(data):,}개")
    return data


# ------------------------------------------------------------
# 집계
# ------------------------------------------------------------
def _add_pitch_flags(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    hand = d["p_throws"].map({"R": -1.0, "L": 1.0})
    d["ivb_in"] = d["pfx_z"] * 12.0
    d["hb_in"] = d["pfx_x"] * 12.0 * hand          # 암사이드 양수
    d["is_swing"] = d["description"].isin(SWING_DESC)
    d["is_whiff"] = d["description"].isin(WHIFF_DESC)
    d["is_csw"] = d["description"].isin(WHIFF_DESC | CALLED_STRIKE_DESC)
    if "zone" in d.columns:
        d["is_out_zone"] = d["zone"].between(11, 14)
    else:
        d["is_out_zone"] = False
    d["is_chase"] = d["is_out_zone"] & d["is_swing"]
    # delta_run_exp는 타격팀 기준 → 투수 기준으로 부호 반전
    d["rv_pitcher"] = -d["delta_run_exp"] if "delta_run_exp" in d.columns else np.nan
    # 인플레이 타구(BBE) 지표: GB% = 땅볼/BBE, xwOBAcon = BBE의 기대 wOBA 평균
    bb = d["bb_type"] if "bb_type" in d.columns else pd.Series(np.nan, index=d.index)
    d["is_bbe"] = bb.notna()
    d["is_gb"] = bb == "ground_ball"
    d["xwoba_bbe"] = (d["estimated_woba_using_speedangle"].where(d["is_bbe"])
                      if "estimated_woba_using_speedangle" in d.columns else np.nan)
    return d


def build_arsenal_table(data: pd.DataFrame) -> pd.DataFrame:
    """투수-시즌-구종 단위 요약표."""
    d = _add_pitch_flags(data)
    keys = ["pitcher", "game_year", "pitch_type"]

    g = d.groupby(keys, observed=True)
    ars = g.agg(
        player_name=("player_name", "first"),
        p_throws=("p_throws", "first"),
        pitch_name=("pitch_name", "first") if "pitch_name" in d.columns else ("pitch_type", "first"),
        n=("pitch_type", "size"),
        velo_mph=("release_speed", "mean"),
        ivb_in=("ivb_in", "mean"),
        hb_in=("hb_in", "mean"),
        spin_rpm=("release_spin_rate", "mean"),
        extension_ft=("release_extension", "mean"),
        arm_angle_deg=("arm_angle", "mean"),
        release_x_ft=("release_pos_x", "mean"),
        release_z_ft=("release_pos_z", "mean"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        csw=("is_csw", "sum"),
        out_zone=("is_out_zone", "sum"),
        chases=("is_chase", "sum"),
        rv_sum=("rv_pitcher", "sum"),
        rv_n=("rv_pitcher", "count"),
        n_bbe=("is_bbe", "sum"),
        gbs=("is_gb", "sum"),
        xwobacon=("xwoba_bbe", "mean"),
    ).reset_index()

    # 비율 지표
    ars["whiff_pct"] = 100 * ars["whiffs"] / ars["swings"].replace(0, np.nan)
    ars["csw_pct"] = 100 * ars["csw"] / ars["n"]
    ars["chase_pct"] = 100 * ars["chases"] / ars["out_zone"].replace(0, np.nan)
    ars["rv_per_100"] = 100 * ars["rv_sum"] / ars["rv_n"].replace(0, np.nan)
    ars["gb_pct"] = 100 * ars["gbs"] / ars["n_bbe"].replace(0, np.nan)

    # 구사율 (전체 / 좌타 / 우타)
    total = d.groupby(["pitcher", "game_year"]).size().rename("season_total")
    ars = ars.merge(total, on=["pitcher", "game_year"])
    ars["usage_pct"] = 100 * ars["n"] / ars["season_total"]
    for side in ("L", "R"):
        ds = d[d["stand"] == side]
        side_n = ds.groupby(keys, observed=True).size().rename("_side_n").reset_index()
        side_total = ds.groupby(["pitcher", "game_year"]).size().rename("_side_total").reset_index()
        side_n = side_n.merge(side_total, on=["pitcher", "game_year"])
        side_n[f"usage_vs_{side}HH_pct"] = 100 * side_n["_side_n"] / side_n["_side_total"]
        ars = ars.merge(side_n[[*keys, f"usage_vs_{side}HH_pct"]], on=keys, how="left")

    # 주 패스트볼(FF/SI/FC 중 최다) 및 패스트볼 대비 차이
    fb = ars[ars["pitch_type"].isin(FASTBALL_TYPES)]
    primary = fb.loc[fb.groupby(["pitcher", "game_year"])["n"].idxmax(),
                     ["pitcher", "game_year", "pitch_type", "velo_mph", "ivb_in", "hb_in"]]
    primary = primary.rename(columns={"pitch_type": "primary_fastball",
                                      "velo_mph": "_fb_velo", "ivb_in": "_fb_ivb", "hb_in": "_fb_hb"})
    ars = ars.merge(primary, on=["pitcher", "game_year"], how="left")
    ars["is_primary_fastball"] = ars["pitch_type"] == ars["primary_fastball"]
    ars["velo_gap_vs_fb"] = ars["velo_mph"] - ars["_fb_velo"]
    ars["ivb_gap_vs_fb"] = ars["ivb_in"] - ars["_fb_ivb"]
    ars["hb_gap_vs_fb"] = ars["hb_in"] - ars["_fb_hb"]
    ars["small_sample"] = ars["n"] < SMALL_SAMPLE_PITCHES

    drop = ["gbs", "swings", "whiffs", "csw", "out_zone", "chases", "rv_sum", "rv_n", "_fb_velo", "_fb_ivb", "_fb_hb"]
    return ars.drop(columns=drop).sort_values(["pitcher", "game_year", "n"],
                                              ascending=[True, True, False]).reset_index(drop=True)


def load_arsenal(force_rerun: bool = False) -> pd.DataFrame:
    """캐시가 있으면 불러오고, 없으면 raw에서 계산 후 저장."""
    if ARSENAL_PKL.exists() and not force_rerun:
        cached = pd.read_pickle(ARSENAL_PKL)
        if {"gb_pct", "xwobacon", "n_bbe"}.issubset(cached.columns):   # 예전 버전 캐시면 다시 계산
            return cached
    ars = build_arsenal_table(load_raw_pitches())
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    ars.to_pickle(ARSENAL_PKL)
    print(f"[arsenal] 저장: {rel(ARSENAL_PKL)} ({len(ars):,}행)")
    return ars


def _r(x, nd=1):
    return None if pd.isna(x) else round(float(x), nd)


def pitcher_season_summary(arsenal: pd.DataFrame, pitcher_id: int, year: int) -> dict:
    """한 투수-시즌을 프롬프트에 넣을 dict로 요약한다."""
    rows = arsenal[(arsenal["pitcher"] == pitcher_id) & (arsenal["game_year"] == int(year))]
    if rows.empty:
        raise ValueError(f"투수 {pitcher_id}의 {year} 시즌 데이터가 없습니다.")
    rows = rows[rows["n"] >= MIN_PITCHES_TO_LIST]

    fb = rows[rows["is_primary_fastball"]]
    fb = fb.iloc[0] if not fb.empty else None
    first = rows.iloc[0]

    pitches = []
    for _, r in rows.iterrows():
        pitches.append({
            "pitch_type": r["pitch_type"],
            "pitch_name": r["pitch_name"],
            "is_primary_fastball": bool(r["is_primary_fastball"]),
            "n_pitches": int(r["n"]),
            "small_sample": bool(r["small_sample"]),
            "usage_pct": _r(r["usage_pct"]),
            "usage_vs_LHH_pct": _r(r.get("usage_vs_LHH_pct")),
            "usage_vs_RHH_pct": _r(r.get("usage_vs_RHH_pct")),
            "velo_mph": _r(r["velo_mph"]),
            "ivb_in": _r(r["ivb_in"]),
            "hb_in": _r(r["hb_in"]),
            "spin_rpm": _r(r["spin_rpm"], 0),
            "velo_gap_vs_fb": _r(r["velo_gap_vs_fb"]),
            "ivb_gap_vs_fb": _r(r["ivb_gap_vs_fb"]),
            "hb_gap_vs_fb": _r(r["hb_gap_vs_fb"]),
            "whiff_pct": _r(r["whiff_pct"]),
            "csw_pct": _r(r["csw_pct"]),
            "chase_pct": _r(r["chase_pct"]),
            "rv_per_100": _r(r["rv_per_100"], 2),
            "n_bbe": int(r["n_bbe"]),
            "gb_pct": _r(r["gb_pct"]),
            "xwobacon": _r(r["xwobacon"], 3),
        })

    return {
        "pitcher_id": int(pitcher_id),
        "player_name": first["player_name"],
        "season": int(year),
        "throws": first["p_throws"],
        "primary_fastball": None if fb is None else {
            "pitch_type": fb["pitch_type"],
            "velo_mph": _r(fb["velo_mph"]),
            "ivb_in": _r(fb["ivb_in"]),
            "hb_in": _r(fb["hb_in"]),
            "spin_rpm": _r(fb["spin_rpm"], 0),
            "arm_angle_deg": _r(fb["arm_angle_deg"]),
            "extension_ft": _r(fb["extension_ft"]),
            "release_height_ft": _r(fb["release_z_ft"]),
            "release_side_ft": _r(abs(fb["release_x_ft"]) if pd.notna(fb["release_x_ft"]) else np.nan),
        },
        "arsenal": pitches,
    }


def transfer_targets(input_summary: dict, similar_summary: dict) -> list[dict]:
    """유사 투수의 (변화구 − 패스트볼) 차이를 입력 투수의 패스트볼에 더해 목표 shape를 계산한다.

    GPT가 산술을 틀리지 않도록 코드에서 미리 계산해 넘긴다.
    """
    fb_in = input_summary.get("primary_fastball")
    if fb_in is None or None in (fb_in["velo_mph"], fb_in["ivb_in"], fb_in["hb_in"]):
        return []
    input_types = {p["pitch_type"]: p for p in input_summary["arsenal"]}

    out = []
    for p in similar_summary["arsenal"]:
        if p["is_primary_fastball"] or None in (p["velo_gap_vs_fb"], p["ivb_gap_vs_fb"], p["hb_gap_vs_fb"]):
            continue
        target = {
            "pitch_type": p["pitch_type"],
            "pitch_name": p["pitch_name"],
            "source_usage_pct": p["usage_pct"],
            "source_n_pitches": p["n_pitches"],
            "source_small_sample": p["small_sample"],
            "gap_vs_fb": {"velo_mph": p["velo_gap_vs_fb"], "ivb_in": p["ivb_gap_vs_fb"], "hb_in": p["hb_gap_vs_fb"]},
            "target_shape": {
                "velo_mph": round(fb_in["velo_mph"] + p["velo_gap_vs_fb"], 1),
                "ivb_in": round(fb_in["ivb_in"] + p["ivb_gap_vs_fb"], 1),
                "hb_in": round(fb_in["hb_in"] + p["hb_gap_vs_fb"], 1),
            },
            "input_already_throws": p["pitch_type"] in input_types,
        }
        if target["input_already_throws"]:
            cur = input_types[p["pitch_type"]]
            target["input_current_shape"] = {"velo_mph": cur["velo_mph"], "ivb_in": cur["ivb_in"], "hb_in": cur["hb_in"]}
        out.append(target)
    return out


# ============================================================
# 2. 프롬프트 (시스템 프롬프트 + one-shot 예시 + 출력 스키마)
# ============================================================
# ------------------------------------------------------------
# 출력 JSON 스키마 (시스템 프롬프트에 그대로 들어가고, 코드 검증에도 사용)
# ------------------------------------------------------------
OUTPUT_SCHEMA = {
    "summary": "string — 2~3문장. 두 투수 패스트볼의 공통점과 핵심 추천을 요약",
    "fastball_comparison": {
        "similarities": ["string — 수치 포함 (예: '팔 각도 45.9° vs 44.1°')"],
        "differences": ["string — 수치 포함"],
    },
    "recommendations": [
        {
            "rank": "integer 1~3",
            "pitch_type": "string — Statcast 코드 (예: ST, SL, CH). 반드시 입력 데이터에 존재하는 코드",
            "pitch_name": "string",
            "action": "'add'(새로 추가) | 'refine'(이미 던지는 구종의 shape 조정) | 'usage'(구사율/사용 상황 조정)",
            "target_shape": {"velo_mph": "number", "ivb_in": "number", "hb_in": "number"},
            "gap_vs_fastball": {"velo_mph": "number", "ivb_in": "number", "hb_in": "number"},
            "rationale": ["string — 근거 2~4개, 각 근거에 입력 데이터의 수치를 인용"],
            "usage_plan": "string — 어떤 타자(좌/우)·상황에 쓰는지, 유사 투수의 좌/우타 구사율 근거",
            "confidence": "'high' | 'medium' | 'low'",
            "caveats": ["string — 표본 크기, 구현 난이도 등"],
        }
    ],
    "failure_cases": [
        {"pitcher": "'input' | 'similar'", "pitch_type": "string",
         "lesson": "string — 성과가 나빴던 구종(RV/100 음수, xwOBAcon 높음 등)에서 피해야 할 shape/사용법 (수치 인용)"}
    ],
    "not_recommended": [
        {"pitch_type": "string", "reason": "string — 유사 투수가 던졌지만 추천하지 않는 이유 (수치 인용)"}
    ],
    "data_limitations": ["string — 이 추천의 한계"],
}

SYSTEM_PROMPT = f"""당신은 MLB 투구 설계(pitch design) 분석가입니다.
대학 연구 프로젝트 '주 패스트볼 shape 기반 개인화 변화구 추천'의 마지막 단계에서,
[입력 투수]와 패스트볼이 비슷하지만 성적이 더 좋았던 [유사 투수]의 Statcast 집계 데이터를 비교해
입력 투수에게 맞는 변화구(세컨더리 피치) shape 목표를 최대 3개 제시합니다.

## 입력 데이터 정의
- 모든 수치는 해당 시즌 MLB 정규시즌 Statcast 투구 데이터에서 계산한 값입니다.
- velo_mph: 평균 구속(mph). ivb_in: 수직 무브먼트(인치, 중력 제외, +는 떠오름).
- hb_in: 수평 무브먼트(인치). **암사이드(투수 팔 쪽) = +, 글러브사이드 = −** 로 좌/우완 통일.
- *_gap_vs_fb: 같은 투수의 주 패스트볼 대비 차이(해당 구종 − 주 패스트볼).
- whiff_pct: 헛스윙/스윙(%). chase_pct: 존 밖 공에 대한 스윙 비율(%).
- primary_fastball: 주 패스트볼의 릴리스 기하(팔 각도, 익스텐션, 릴리스 높이/좌우). 구속·무브먼트는 arsenal의 해당 구종 참고.
- rv_per_100: 100구당 투수 기준 런 밸류. **+일수록 투수에게 좋음**. (주 성과지표)
- gb_pct: 인플레이 타구(BBE) 중 땅볼 비율(%). xwobacon: BBE의 기대 wOBA 평균, **낮을수록 투수에게 좋음** (리그 평균 약 0.370 내외).
- n_bbe: 인플레이 타구 수. 30개 미만이면 gb_pct·xwobacon은 불안정합니다.
- small_sample=true: 100구 미만 → 비율 지표가 불안정함.
- transfer_targets: 코드가 미리 계산한 목표 shape = 입력 투수 주 패스트볼 + 유사 투수의 (구종 − 패스트볼) 차이.
- search_context: 유사 투수 검색 단계에서 넘어온 정보(클러스터, 거리, FIP 등). 없을 수도 있습니다.

## 반드시 지킬 규칙
1. 입력 JSON에 있는 수치만 사용하세요. 선수에 대한 사전 지식, 다른 시즌 기록, 부상·뉴스·코칭 정보는 쓰지 마세요.
   선수 이름은 식별용일 뿐입니다.
2. 추천 구종(pitch_type)은 (a) 유사 투수의 arsenal에 있는 구종, 또는 (b) 입력 투수가 이미 던지는 구종의 조정만 허용됩니다.
   데이터에 없는 구종을 만들지 마세요.
3. target_shape와 gap_vs_fastball은 transfer_targets의 값을 그대로 사용하세요. 직접 새로 계산하지 마세요.
   action이 'usage'면 입력 투수의 현재 shape를 target_shape에 넣으세요.
4. 각 rationale 항목에는 입력 데이터의 숫자를 최소 1개 인용하세요 (예: "유사 투수 ST whiff 38.2%, RV/100 +1.9").
5. 추천 우선순위:
   (1) 성과: 유사 투수에게서 rv_per_100이 좋았던 구종
   (2) 역할별 메커니즘: 구종 역할에 맞는 지표로 성공 이유를 확인하세요.
       - 스위퍼·슬라이더·커브(ST, SL, SV, CU, KC): whiff_pct, chase_pct
       - 체인지업·스플리터(CH, FS, FO): whiff_pct, gb_pct, xwobacon
       - 커터·싱커(FC, SI): whiff_pct, xwobacon(약한 컨택)
   (3) 분리: 입력 투수 패스트볼과의 구속·무브먼트 차이
   (4) 역할 보완: 입력 투수에게 없거나 성과가 나쁜 역할(예: 반대손 타자 대응 구종)을 채우는지
5-1. 실패 사례: 유사 투수 또는 입력 투수의 구종 중 rv_per_100이 음수이거나 xwobacon이 높은 구종이 있으면
   failure_cases에 "어떤 shape/사용법을 피해야 하는지"를 수치와 함께 1~2개 쓰세요. 해당 사례가 없으면 빈 리스트로 두세요.
6. 표본이 작거나(small_sample, 또는 n_bbe 30 미만인데 gb_pct·xwobacon을 근거로 쓸 때) 구사율이 5% 미만인 구종은 confidence를 'low'로 두고 caveats에 이유를 쓰세요.
7. 관측 데이터 기반 추천입니다. "이 구종을 익히면 성적이 오른다" 같은 인과적 단정은 하지 말고
   "유사한 패스트볼을 가진 투수에게서 효과적이었다" 수준으로 표현하세요. 부상 위험·그립 등 생체역학은 판단하지 마세요.
8. 근거가 부족하면 추천을 3개보다 적게 내도 됩니다. 억지로 채우지 마세요.
9. 한국어로 작성하되 구종 코드(FF, SL, ST 등)와 지표명(IVB, HB, Whiff%)은 영어 그대로 쓰세요.

## 출력 형식
아래 스키마를 따르는 JSON 객체 하나만 출력하세요. 코드 블록(```)이나 다른 설명 문장은 붙이지 마세요.
{json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}
"""

# ------------------------------------------------------------
# one-shot 예시 (가상의 투수 — 실제 선수 아님)
# ------------------------------------------------------------
ONE_SHOT_USER = {
    "task": "입력 투수에게 맞는 변화구 shape 목표를 최대 3개 추천",
    "search_context": {"cluster": 0, "fastball_distance": 0.42, "input_fip": 4.61, "similar_fip": 3.38},
    "input_pitcher": {
        "player_name": "예시 투수 A (가상)", "season": 2024, "throws": "R",
        "primary_fastball": {"pitch_type": "FF", "velo_mph": 94.0, "ivb_in": 15.8, "hb_in": 7.5,
                             "spin_rpm": 2350, "arm_angle_deg": 44.0, "extension_ft": 6.4,
                             "release_height_ft": 5.9, "release_side_ft": 1.9},
        "arsenal": [
            {"pitch_type": "FF", "pitch_name": "4-Seam Fastball", "is_primary_fastball": True, "n_pitches": 1180,
             "small_sample": False, "usage_pct": 55.0, "usage_vs_LHH_pct": 57.0, "usage_vs_RHH_pct": 53.0,
             "velo_mph": 94.0, "ivb_in": 15.8, "hb_in": 7.5, "spin_rpm": 2350,
             "velo_gap_vs_fb": 0.0, "ivb_gap_vs_fb": 0.0, "hb_gap_vs_fb": 0.0,
             "whiff_pct": 21.0, "csw_pct": 27.5, "chase_pct": 22.0, "rv_per_100": -0.4},
            {"pitch_type": "SL", "pitch_name": "Slider", "is_primary_fastball": False, "n_pitches": 640,
             "small_sample": False, "usage_pct": 30.0, "usage_vs_LHH_pct": 18.0, "usage_vs_RHH_pct": 41.0,
             "velo_mph": 86.5, "ivb_in": 3.0, "hb_in": -3.5, "spin_rpm": 2400,
             "velo_gap_vs_fb": -7.5, "ivb_gap_vs_fb": -12.8, "hb_gap_vs_fb": -11.0,
             "whiff_pct": 29.0, "csw_pct": 29.0, "chase_pct": 30.0, "rv_per_100": 0.3},
            {"pitch_type": "CH", "pitch_name": "Changeup", "is_primary_fastball": False, "n_pitches": 320,
             "small_sample": False, "usage_pct": 15.0, "usage_vs_LHH_pct": 25.0, "usage_vs_RHH_pct": 6.0,
             "velo_mph": 87.5, "ivb_in": 9.5, "hb_in": 12.5, "spin_rpm": 1800,
             "velo_gap_vs_fb": -6.5, "ivb_gap_vs_fb": -6.3, "hb_gap_vs_fb": 5.0,
             "whiff_pct": 24.0, "csw_pct": 24.0, "chase_pct": 26.0, "rv_per_100": -1.6},
        ],
    },
    "similar_pitcher": {
        "player_name": "예시 투수 B (가상)", "season": 2023, "throws": "R",
        "primary_fastball": {"pitch_type": "FF", "velo_mph": 94.6, "ivb_in": 16.4, "hb_in": 7.0,
                             "spin_rpm": 2380, "arm_angle_deg": 45.5, "extension_ft": 6.5,
                             "release_height_ft": 6.0, "release_side_ft": 1.8},
        "arsenal": [
            {"pitch_type": "FF", "pitch_name": "4-Seam Fastball", "is_primary_fastball": True, "n_pitches": 1100,
             "small_sample": False, "usage_pct": 48.0, "usage_vs_LHH_pct": 50.0, "usage_vs_RHH_pct": 46.0,
             "velo_mph": 94.6, "ivb_in": 16.4, "hb_in": 7.0, "spin_rpm": 2380,
             "velo_gap_vs_fb": 0.0, "ivb_gap_vs_fb": 0.0, "hb_gap_vs_fb": 0.0,
             "whiff_pct": 24.0, "csw_pct": 29.0, "chase_pct": 24.0, "rv_per_100": 0.8},
            {"pitch_type": "ST", "pitch_name": "Sweeper", "is_primary_fastball": False, "n_pitches": 560,
             "small_sample": False, "usage_pct": 25.0, "usage_vs_LHH_pct": 12.0, "usage_vs_RHH_pct": 38.0,
             "velo_mph": 83.0, "ivb_in": 1.0, "hb_in": -14.0, "spin_rpm": 2650,
             "velo_gap_vs_fb": -11.6, "ivb_gap_vs_fb": -15.4, "hb_gap_vs_fb": -21.0,
             "whiff_pct": 37.0, "csw_pct": 33.0, "chase_pct": 33.0, "rv_per_100": 1.9},
            {"pitch_type": "FS", "pitch_name": "Split-Finger", "is_primary_fastball": False, "n_pitches": 390,
             "small_sample": False, "usage_pct": 17.0, "usage_vs_LHH_pct": 29.0, "usage_vs_RHH_pct": 6.0,
             "velo_mph": 86.0, "ivb_in": 4.5, "hb_in": 10.0, "spin_rpm": 1350,
             "velo_gap_vs_fb": -8.6, "ivb_gap_vs_fb": -11.9, "hb_gap_vs_fb": 3.0,
             "whiff_pct": 36.0, "csw_pct": 30.0, "chase_pct": 35.0, "rv_per_100": 1.4},
            {"pitch_type": "CU", "pitch_name": "Curveball", "is_primary_fastball": False, "n_pitches": 70,
             "small_sample": True, "usage_pct": 3.0, "usage_vs_LHH_pct": 4.0, "usage_vs_RHH_pct": 2.0,
             "velo_mph": 79.0, "ivb_in": -9.0, "hb_in": -8.0, "spin_rpm": 2700,
             "velo_gap_vs_fb": -15.6, "ivb_gap_vs_fb": -25.4, "hb_gap_vs_fb": -15.0,
             "whiff_pct": 30.0, "csw_pct": 31.0, "chase_pct": 20.0, "rv_per_100": 2.5},
        ],
    },
    "transfer_targets": [
        {"pitch_type": "ST", "pitch_name": "Sweeper", "source_usage_pct": 25.0, "source_n_pitches": 560,
         "source_small_sample": False, "gap_vs_fb": {"velo_mph": -11.6, "ivb_in": -15.4, "hb_in": -21.0},
         "target_shape": {"velo_mph": 82.4, "ivb_in": 0.4, "hb_in": -13.5}, "input_already_throws": False},
        {"pitch_type": "FS", "pitch_name": "Split-Finger", "source_usage_pct": 17.0, "source_n_pitches": 390,
         "source_small_sample": False, "gap_vs_fb": {"velo_mph": -8.6, "ivb_in": -11.9, "hb_in": 3.0},
         "target_shape": {"velo_mph": 85.4, "ivb_in": 3.9, "hb_in": 10.5}, "input_already_throws": False},
        {"pitch_type": "CU", "pitch_name": "Curveball", "source_usage_pct": 3.0, "source_n_pitches": 70,
         "source_small_sample": True, "gap_vs_fb": {"velo_mph": -15.6, "ivb_in": -25.4, "hb_in": -15.0},
         "target_shape": {"velo_mph": 78.4, "ivb_in": -9.6, "hb_in": -7.5}, "input_already_throws": False},
    ],
}

# one-shot 예시 투구에 BBE 지표 추가 (가상 수치): (n_bbe, gb_pct, xwobacon)
_EXAMPLE_BBE = {
    ("input_pitcher", "FF"): (210, 33.0, 0.395), ("input_pitcher", "SL"): (105, 40.0, 0.350),
    ("input_pitcher", "CH"): (70, 38.0, 0.430),
    ("similar_pitcher", "FF"): (190, 31.0, 0.360), ("similar_pitcher", "ST"): (80, 42.0, 0.310),
    ("similar_pitcher", "FS"): (65, 55.0, 0.300), ("similar_pitcher", "CU"): (12, 50.0, 0.280),
}
for _who in ("input_pitcher", "similar_pitcher"):
    for _p in ONE_SHOT_USER[_who]["arsenal"]:
        _p["n_bbe"], _p["gb_pct"], _p["xwobacon"] = _EXAMPLE_BBE[(_who, _p["pitch_type"])]

ONE_SHOT_ASSISTANT = {
    "summary": "두 투수는 94mph대 라이징 포심(IVB 15.8 vs 16.4in)과 비슷한 팔 각도(44.0° vs 45.5°)를 공유합니다. "
               "유사 투수 B의 성과를 이끈 스위퍼와 스플리터를 입력 투수 A의 패스트볼 기준 목표 shape로 옮기는 것을 우선 추천합니다.",
    "fastball_comparison": {
        "similarities": ["구속 94.0 vs 94.6mph, IVB 15.8 vs 16.4in로 거의 같은 라이징 포심",
                         "팔 각도 44.0° vs 45.5°, 익스텐션 6.4 vs 6.5ft로 릴리스 기하가 유사"],
        "differences": ["포심 RV/100이 A -0.4, B +0.8로 B가 더 효과적",
                        "B는 포심 구사율 48%로 A(55%)보다 변화구 비중이 높음"],
    },
    "recommendations": [
        {"rank": 1, "pitch_type": "ST", "pitch_name": "Sweeper", "action": "add",
         "target_shape": {"velo_mph": 82.4, "ivb_in": 0.4, "hb_in": -13.5},
         "gap_vs_fastball": {"velo_mph": -11.6, "ivb_in": -15.4, "hb_in": -21.0},
         "rationale": ["B의 ST는 whiff 37.0%, RV/100 +1.9로 B 아스날 중 표본이 충분한 구종 가운데 가장 효과적",
                       "A의 현재 SL(HB -3.5in)보다 글러브사이드로 10in 더 휘어 포심과 좌우 분리가 커짐",
                       "B는 우타자 상대 ST 구사율 38%로, A의 우타자 상대 SL(41%) 역할을 대체·보강할 수 있음"],
         "usage_plan": "우타자 상대 주 결정구. B처럼 우타자 상대 30~40% 수준에서 시작",
         "confidence": "high",
         "caveats": ["A의 SL과 그립·회전 방식이 달라 구현 난이도는 데이터로 판단할 수 없음"]},
        {"rank": 2, "pitch_type": "FS", "pitch_name": "Split-Finger", "action": "add",
         "target_shape": {"velo_mph": 85.4, "ivb_in": 3.9, "hb_in": 10.5},
         "gap_vs_fastball": {"velo_mph": -8.6, "ivb_in": -11.9, "hb_in": 3.0},
         "rationale": ["A의 CH는 RV/100 -1.6, xwOBAcon 0.430으로 좌타자 대응 구종이 약함",
                       "B의 FS는 whiff 36.0%, GB 55.0%, xwOBAcon 0.300, RV/100 +1.4이고 좌타자 상대 구사율 29%",
                       "FS 목표 IVB 3.9in는 A의 CH(9.5in)보다 5.6in 더 떨어져 포심과 수직 분리가 큼"],
         "usage_plan": "좌타자 상대 체인지업 대체 구종으로 사용",
         "confidence": "medium",
         "caveats": ["A의 CH를 대체할지 병행할지는 데이터로 결정할 수 없음",
                     "B의 FS 인플레이 타구는 65개로 GB%·xwOBAcon은 참고 수준"]},
    ],
    "failure_cases": [
        {"pitcher": "input", "pitch_type": "CH",
         "lesson": "A의 CH는 IVB 9.5in로 포심(15.8in)과 수직 차이가 6.3in에 그쳐 xwOBAcon 0.430, RV/100 -1.6. "
                   "새 오프스피드는 포심 대비 IVB 차이 10in 이상을 목표로 해야 함"}
    ],
    "not_recommended": [
        {"pitch_type": "CU", "reason": "B의 CU는 RV/100 +2.5지만 70구(small_sample)·구사율 3.0%로 근거가 불충분"}
    ],
    "data_limitations": ["단일 시즌 관측 데이터 기반이며 인과 효과가 아님",
                         "타자 구성, 구장, 카운트 등 상황 변수는 반영되지 않음"],
}


# 프롬프트 길이 절약: 중복되거나 판단에 덜 중요한 값은 GPT에 보낼 때만 뺀다 (저장되는 payload는 그대로)
_DROP_PITCH_KEYS = {"csw_pct"}
_DROP_FB_KEYS = {"velo_mph", "ivb_in", "hb_in", "spin_rpm"}          # arsenal의 주 패스트볼 항목과 중복
_DROP_TARGET_KEYS = {"source_usage_pct", "source_n_pitches", "source_small_sample"}  # arsenal과 중복


def compact_payload(payload: dict) -> dict:
    out = json.loads(json.dumps(payload))
    out.pop("task", None)
    for who in ("input_pitcher", "similar_pitcher"):
        p = out.get(who, {})
        if p.get("primary_fastball"):
            p["primary_fastball"] = {k: v for k, v in p["primary_fastball"].items() if k not in _DROP_FB_KEYS}
        p["arsenal"] = [{k: v for k, v in a.items() if k not in _DROP_PITCH_KEYS} for a in p.get("arsenal", [])]
    out["transfer_targets"] = [{k: v for k, v in t.items() if k not in _DROP_TARGET_KEYS}
                               for t in out.get("transfer_targets", [])]
    return out


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))   # 공백 없이 (토큰 절약)


def build_messages(payload: dict, one_shot: bool = True) -> list[dict]:
    """system → one-shot(user/assistant) → 실제 요청(user) 순서의 messages.

    one_shot=False: 무료 API의 입력 길이 한도를 넘을 때 예시를 빼고 보낸다 (형식은 시스템 프롬프트의 스키마로 유지).
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if one_shot:
        messages += [
            {"role": "user", "content": _dumps(compact_payload(ONE_SHOT_USER))},
            {"role": "assistant", "content": _dumps(ONE_SHOT_ASSISTANT)},
        ]
    messages.append({"role": "user", "content": _dumps(compact_payload(payload))})
    return messages


# ============================================================
# 3. LLM 호출 (Gemini / OpenAI — OpenAI 공식 SDK 사용, 키는 .env에서 읽음)
# ============================================================
# OpenAI 호환 방식으로 접속할 수 있는 제공자 (OpenAI SDK 그대로 사용, 주소만 다름)
PROVIDERS = {
    "openai": {"key_env": "OPENAI_API_KEY", "base_url": None, "default_model": "gpt-5-mini"},
    "gemini": {"key_env": "GEMINI_API_KEY",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "default_model": "gemini-3.8-flash",
               # 기본 모델이 혼잡(503)·한도 초과(429)일 때 차례로 시도할 무료 모델
               "fallback_models": ["gemini-3.7-flash", "gemini-3.5-flash-lite"]},
}
TRANSIENT_RETRIES = 3            # 일시적 오류 때 같은 모델로 재시도 횟수 (2초, 4초, 8초 대기)
_sleep = time.sleep              # 테스트에서 대기 없이 돌릴 수 있게 분리
MAX_RETRIES = 4


def resolve_provider() -> tuple[str, str | None]:
    """.env를 읽고 (제공자, API 키)를 정한다. OPENAI_API_KEY가 있으면 OpenAI, 없고 GEMINI_API_KEY가 있으면 Gemini."""
    load_dotenv(ROOT / ".env")                 # 레포 루트의 .env
    if os.getenv("OPENAI_API_KEY"):
        return "openai", os.getenv("OPENAI_API_KEY")
    if os.getenv("GEMINI_API_KEY"):
        return "gemini", os.getenv("GEMINI_API_KEY")
    return "none", None


def default_model() -> str:
    provider, _ = resolve_provider()
    return os.getenv("LLM_MODEL") or PROVIDERS.get(provider, PROVIDERS["gemini"])["default_model"]


def get_client():
    provider, api_key = resolve_provider()
    if not api_key:
        raise RuntimeError(
            "API 키가 없습니다. 레포 루트의 .env에 GEMINI_API_KEY=... (무료) 또는 "
            "OPENAI_API_KEY=... 를 적어주세요. 코드에 직접 쓰지 마세요."
        )
    from openai import OpenAI                   # dry-run 때는 설치 안 돼 있어도 되게 여기서 import
    return OpenAI(api_key=api_key, base_url=PROVIDERS[provider]["base_url"])

class TransientLLMError(RuntimeError):
    """서버 혼잡·한도 초과처럼 잠시 뒤 다시 하면 될 수 있는 오류."""


_TRANSIENT_MARKERS = ("503", "unavailable", "overloaded", "high demand", "429", "rate limit",
                      "resource_exhausted", "quota", "timeout", "timed out", "temporarily", "try again later")


def _is_transient(msg: str) -> bool:
    return any(m in msg for m in _TRANSIENT_MARKERS)


def call_gpt(messages: list[dict], client=None, model: str | None = None) -> tuple[dict, str]:
    """한 모델로 호출. 일시적 오류는 대기 후 재시도하고, 그래도 안 되면 TransientLLMError."""
    client = client or get_client()
    model = model or default_model()

    last_err = None
    use_json_mode = True
    attempts, transient_tries = 0, 0
    while attempts < MAX_RETRIES:
        attempts += 1
        try:
            kwargs = {"response_format": {"type": "json_object"}} if use_json_mode else {}   # JSON만 반환하도록 강제
            resp = client.chat.completions.create(model=model, messages=messages, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if use_json_mode and "response_format" in msg:   # JSON 모드를 지원하지 않는 모델이면 빼고 재시도
                print("[LLM] 이 모델은 JSON 모드를 지원하지 않아 끄고 다시 요청합니다 (형식은 프롬프트로 유지).")
                use_json_mode = False
                continue
            too_long = "token" in msg and any(w in msg for w in ("limit", "too large", "too long", "maximum"))
            if too_long and len(messages) == 4:            # one-shot 포함 상태면 빼고 한 번 더
                print("[LLM] 입력 길이 한도 초과 → one-shot 예시를 빼고 다시 요청합니다.")
                messages = [messages[0], messages[-1]]
                continue
            if _is_transient(msg):                         # 서버 혼잡·한도 초과 → 잠시 기다렸다 재시도
                if transient_tries < TRANSIENT_RETRIES:
                    wait = 2 ** (transient_tries + 1)
                    transient_tries += 1
                    attempts -= 1                          # 대기 재시도는 횟수에 넣지 않음
                    print(f"[LLM] {model} 일시적 오류 → {wait}초 뒤 재시도 ({transient_tries}/{TRANSIENT_RETRIES})")
                    _sleep(wait)
                    continue
                raise TransientLLMError(f"{model}: {e}") from None
            raise
        text = _response_text(resp)
        try:
            return json.loads(_strip_code_fence(text)), model
        except json.JSONDecodeError as e:
            last_err = e
            print(f"[LLM] JSON 파싱 실패 (시도 {attempts}/{MAX_RETRIES}), 재시도")
    raise RuntimeError(f"LLM 응답을 JSON으로 읽지 못했습니다: {last_err}")


def call_llm_with_fallback(messages: list[dict], client=None, model: str | None = None) -> tuple[dict, str]:
    """기본 모델이 계속 혼잡하면 대체 모델로 차례로 시도한다.

    대체 모델 목록: .env의 LLM_FALLBACK_MODELS(쉼표 구분)가 있으면 그것, 없으면 제공자 기본값.
    """
    provider, _ = resolve_provider()
    model = model or default_model()
    env = (os.getenv("LLM_FALLBACK_MODELS") or "").strip() or None      # 빈 값이면 기본 대체 순서 사용
    fallbacks = ([m.strip() for m in env.split(",") if m.strip()] if env is not None
                 else PROVIDERS.get(provider, {}).get("fallback_models", []))
    chain = [model] + [m for m in fallbacks if m != model]

    errors = []
    for i, m in enumerate(chain):
        try:
            return call_gpt(messages, client=client, model=m)
        except TransientLLMError as e:
            errors.append(str(e))
            if i + 1 < len(chain):
                print(f"[LLM] {m} 계속 혼잡 → {chain[i + 1]}로 대체 시도")
    raise TransientLLMError("모든 모델이 일시적으로 응답하지 않습니다. 잠시 후 다시 시도하세요. " + " | ".join(errors))


def _response_text(resp) -> str:
    """응답에서 모델이 쓴 텍스트만 꺼낸다.

    보통은 ChatCompletion 객체지만, SDK 버전·서버(GitHub Models 등)에 따라
    JSON 문자열, dict, 스트리밍(data: ...) 문자열로 올 때도 있어 모두 처리한다.
    """
    if isinstance(resp, (bytes, bytearray)):
        resp = resp.decode("utf-8", errors="replace")
    if isinstance(resp, str):
        raw = resp.strip()
        if raw.startswith("data:"):                       # 스트리밍 형식
            parts = []
            for line in raw.splitlines():
                line = line.strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                for ch in chunk.get("choices", []):
                    parts.append((ch.get("delta") or ch.get("message") or {}).get("content") or "")
            return "".join(parts)
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError("API가 예상하지 못한 응답을 보냈습니다 (JSON 아님). 앞부분:\n" + raw[:500])
    if isinstance(resp, dict):
        if "error" in resp:
            raise RuntimeError(f"API 오류 응답: {resp['error']}")
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("응답에 choices가 없습니다. 앞부분:\n" + json.dumps(resp, ensure_ascii=False)[:500])
    return resp.choices[0].message.content or ""


def _strip_code_fence(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


# ============================================================
# 4. 응답 검증 (데이터에 없는 구종, 계산값과 다른 목표 수치, 수치 없는 근거)
# ============================================================
REQUIRED_KEYS = ("summary", "fastball_comparison", "recommendations", "failure_cases",
                 "not_recommended", "data_limitations")


def validate_response(resp: dict, payload: dict, tol: float = 0.25) -> list[str]:
    """스키마와 근거를 점검하고 경고 목록을 돌려준다 (빈 리스트면 통과)."""
    warnings = [f"필수 키 없음: {k}" for k in REQUIRED_KEYS if k not in resp]

    allowed = {p["pitch_type"] for p in payload["similar_pitcher"]["arsenal"]}
    allowed |= {p["pitch_type"] for p in payload["input_pitcher"]["arsenal"]}
    targets = {t["pitch_type"]: t for t in payload["transfer_targets"]}

    recs = resp.get("recommendations", [])
    if len(recs) > 3:
        warnings.append(f"추천이 {len(recs)}개 (최대 3개)")
    for r in recs:
        pt = r.get("pitch_type")
        if pt not in allowed:
            warnings.append(f"[{pt}] 입력 데이터에 없는 구종을 추천함")
            continue
        if r.get("action") not in ("add", "refine", "usage"):
            warnings.append(f"[{pt}] action 값이 잘못됨: {r.get('action')}")
        if r.get("action") in ("add", "refine") and pt in targets:
            want = targets[pt]["target_shape"]
            got = r.get("target_shape") or {}
            for k, v in want.items():
                if not isinstance(got.get(k), (int, float)) or abs(got[k] - v) > tol:
                    warnings.append(f"[{pt}] target_shape.{k}={got.get(k)} ≠ 계산값 {v}")
        if not r.get("rationale"):
            warnings.append(f"[{pt}] 근거(rationale)가 비어 있음")
        elif not all(re.search(r"\d", s) for s in r["rationale"]):
            warnings.append(f"[{pt}] 수치를 인용하지 않은 근거가 있음")
    return warnings


# ------------------------------------------------------------
# 5. 저장 (JSON + Markdown)
# ------------------------------------------------------------


# ============================================================
# 5. 실행 함수
# ============================================================
_lock = threading.Lock()
_arsenal_cache: pd.DataFrame | None = None


def _get_arsenal() -> pd.DataFrame:
    """구종 집계표를 메모리에 한 번만 올려 재사용 (서버에서 요청마다 raw를 다시 읽지 않도록)."""
    global _arsenal_cache
    if _arsenal_cache is None:
        with _lock:
            if _arsenal_cache is None:
                _arsenal_cache = load_arsenal()
    return _arsenal_cache


def _check_pitcher(arsenal: pd.DataFrame, mlbid, year: int) -> int:
    """'pitcher' 값이 mlbid인 투수의 그 시즌 데이터가 있는지 확인하고 int ID를 돌려준다."""
    try:
        pid = int(mlbid)
    except (TypeError, ValueError):
        raise ValueError(f"MLB ID는 숫자여야 합니다: {mlbid!r}") from None
    rows = arsenal[arsenal["pitcher"] == pid]
    if rows.empty:
        raise ValueError(f"MLB ID {pid} 투수의 데이터가 없습니다.")
    if not (rows["game_year"] == int(year)).any():
        years = sorted(rows["game_year"].unique().tolist())
        raise ValueError(f"MLB ID {pid} 투수는 {year} 시즌 투구 데이터가 없습니다. 데이터가 있는 시즌: {years}")
    return pid


def build_payload(input_mlbid, input_year: int, similar_mlbid, similar_year: int,
                  search_context: dict | None = None) -> dict:
    """LLM에 보낼 데이터(두 투수 구종 요약 + 목표 shape)를 만든다. LLM 호출은 하지 않음."""
    arsenal = _get_arsenal()
    in_id = _check_pitcher(arsenal, input_mlbid, input_year)
    sim_id = _check_pitcher(arsenal, similar_mlbid, similar_year)

    in_sum = pitcher_season_summary(arsenal, in_id, int(input_year))
    sim_sum = pitcher_season_summary(arsenal, sim_id, int(similar_year))
    if in_sum["throws"] != sim_sum["throws"]:
        print(f"[llm_client] 주의: 두 투수의 손잡이가 다릅니다 ({in_sum['throws']} vs {sim_sum['throws']}).")

    return {
        "task": "입력 투수에게 맞는 변화구 shape 목표를 최대 3개 추천",
        "search_context": dict(search_context or {}),
        "input_pitcher": in_sum,
        "similar_pitcher": sim_sum,
        "transfer_targets": transfer_targets(in_sum, sim_sum),
    }


def llm_client(input_mlbid, input_year: int, similar_mlbid, similar_year: int,
               search_context: dict | None = None, model: str | None = None) -> dict:
    """입력 투수 + 유사 투수(MLB ID, 연도) → LLM에 넣은 데이터(스탯) + LLM 답변을 담은 dict.

    Args:
        input_mlbid:    추천받을 투수의 MLB ID (Statcast 'pitcher' 값). int 또는 숫자 문자열
        input_year:     그 투수의 시즌 (2021~2025)
        similar_mlbid:  5번 단계가 매칭한 유사 투수의 MLB ID
        similar_year:   유사 투수의 시즌
        search_context: (선택) 5번 단계가 주는 추가 정보. 예: {"cluster": 2, "input_fip": 3.8, "similar_fip": 3.1}
        model:          (선택) 모델 이름. 생략하면 .env의 LLM_MODEL → 제공자 기본값

    Returns:
        {"model", "created_at", "payload"(LLM에 넣은 스탯), "response"(LLM 답변), "validation_warnings"}
        (자세한 구조는 파일 맨 위 설명 참고. 모두 dict/list — JSON 문자열 아님)

    Raises:
        ValueError:        MLB ID가 숫자가 아니거나 해당 시즌 데이터가 없음
        FileNotFoundError: data/raw에 CSV가 없음 (캐시도 없을 때)
        RuntimeError:      API 키 없음, LLM 호출 실패 (TransientLLMError: 서버 혼잡·한도 초과)
    """
    payload = build_payload(input_mlbid, input_year, similar_mlbid, similar_year, search_context)
    response, used_model = call_llm_with_fallback(build_messages(payload), model=model)

    warnings = validate_response(response, payload)
    if warnings:
        print(f"[llm_client] 검증 경고 ({used_model}): " + " / ".join(warnings))
    return {
        "model": used_model,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "payload": payload,
        "response": response,
        "validation_warnings": warnings,
    }


if __name__ == "__main__":
    # 간단 실행 테스트: python -m src.utils.llm_client 660271 2023 434378 2024
    import sys
    if len(sys.argv) != 5:
        print("사용법: python -m src.utils.llm_client <입력 MLB ID> <연도> <유사 MLB ID> <연도>")
        sys.exit(1)
    result = llm_client(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
