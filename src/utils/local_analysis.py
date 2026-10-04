"""Evidence-only comparison when no external LLM credential is configured."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


def _number(value: object) -> float | None:
    try:
        result = float(value) if value is not None else None
        return result if result is not None and isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _display_name(value: object) -> str:
    parts = [part.strip() for part in str(value).split(",", 1)]
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else parts[0]


def build_local_analysis(profiles: dict[str, Any]) -> dict[str, Any]:
    query = profiles["input_pitcher"]
    similar = profiles["similar_pitcher"]
    context = profiles.get("search_context") or {}
    if not query or not similar:
        raise ValueError("비교할 두 투수의 프로필이 필요합니다.")

    input_fb = query.get("primary_fastball") or {}
    similar_fb = similar.get("primary_fastball") or {}
    input_name = _display_name(query.get("player_name", "검색 투수"))
    similar_name = _display_name(similar.get("player_name", "비교 투수"))
    input_fip = _number(context.get("input_fip"))
    similar_fip = _number(context.get("similar_fip"))
    summary = f"{input_name}와 {similar_name}의 관측 구종 지표를 비교했습니다."
    if input_fip is not None and similar_fip is not None:
        summary += f" FIP는 각각 {input_fip:.2f}, {similar_fip:.2f}입니다."
    summary += " 아래 차이는 관측값이며 성적 차이의 원인으로 단정할 수 없습니다."

    similarities: list[str] = []
    differences: list[str] = []
    input_velo = _number(input_fb.get("velo_mph"))
    similar_velo = _number(similar_fb.get("velo_mph"))
    if input_velo is not None and similar_velo is not None:
        similarities.append(f"주 패스트볼 평균 구속은 {input_velo:.1f} / {similar_velo:.1f} mph로 {abs(input_velo - similar_velo):.1f} mph 차이입니다.")
    for key, label in (("ivb_in", "IVB"), ("hb_in", "HB"), ("arm_angle_deg", "팔 각도")):
        left, right = _number(input_fb.get(key)), _number(similar_fb.get(key))
        if left is not None and right is not None:
            unit = "°" if key == "arm_angle_deg" else "in"
            differences.append(f"주 패스트볼 {label}는 {left:.1f}{unit} / {right:.1f}{unit}입니다.")

    candidates = [
        target for target in (profiles.get("transfer_targets") or [])
        if target.get("pitch_type") not in {"FF", "SI", "FC"}
        and (rv := _number(target.get("source_rv_per_100"))) is not None
        and rv >= 0
    ]
    candidates.sort(key=lambda target: (
        not bool(target.get("source_small_sample")),
        _number(target.get("source_rv_per_100")) if _number(target.get("source_rv_per_100")) is not None else float("-inf"),
        _number(target.get("source_n_pitches")) or 0,
    ), reverse=True)

    recommendations = []
    for index, target in enumerate(candidates[:2], start=1):
        shape = target.get("target_shape") or {}
        pitch_name = target.get("pitch_name") or target.get("pitch_type")
        pieces = []
        usage = _number(target.get("source_usage_pct"))
        count = _number(target.get("source_n_pitches"))
        rv = _number(target.get("source_rv_per_100"))
        whiff = _number(target.get("source_whiff_pct"))
        evidence = [f"비교 투수의 {pitch_name}"]
        if usage is not None:
            evidence.append(f"구사율 {usage:.1f}%")
        if count is not None:
            evidence.append(f"{int(count)}구")
        if rv is not None:
            evidence.append(f"RV/100 {rv:+.1f}")
        if whiff is not None:
            evidence.append(f"헛스윙률 {whiff:.1f}%")
        pieces.append(" · ".join(evidence) + "입니다.")
        if all(_number(shape.get(key)) is not None for key in ("velo_mph", "ivb_in", "hb_in")):
            pieces.append(
                "비교 투수의 패스트볼 대비 차이를 옮긴 참고 목표는 "
                f"{float(shape['velo_mph']):.1f} mph, IVB {float(shape['ivb_in']):.1f} in, "
                f"HB {float(shape['hb_in']):.1f} in입니다."
            )
        if target.get("source_small_sample"):
            pieces.append("표본이 100구 미만이어서 성과 지표 해석에 주의가 필요합니다.")
        recommendations.append({
            "rank": index,
            "pitch_type": target.get("pitch_type"),
            "pitch_name": pitch_name,
            "action": "shape 참고 후보",
            "target_shape": shape,
            "rationale": pieces,
            "usage_plan": "실제 구종 구현 가능성과 성적 변화는 별도 검증이 필요합니다.",
        })

    not_recommended = [
        {"pitch_type": target.get("pitch_type"),
         "reason": f"비교 투수의 RV/100 {_number(target['source_rv_per_100']):+.1f}로 0 미만"}
        for target in (profiles.get("transfer_targets") or [])
        if target.get("pitch_type") not in {"FF", "SI", "FC"}
        and _number(target.get("source_rv_per_100")) is not None
        and _number(target.get("source_rv_per_100")) < 0
    ]

    return {
        "model": "Statcast 관측값 기반 참고 분석",
        "source": "rule_based",
        "created_at": datetime.now(timezone.utc).date().isoformat(),
        "response": {
            "summary": summary,
            "fastball_comparison": {"similarities": similarities, "differences": differences},
            "recommendations": recommendations,
            "not_recommended": not_recommended,
        },
        "validation_warnings": ["외부 AI 키가 없어 검증 가능한 수치 비교만 제공했습니다."],
    }
