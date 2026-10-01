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


def build_local_analysis(profiles: dict[str, Any]) -> dict[str, Any]:
    query = profiles["input_pitcher"]
    similar = profiles["similar_pitcher"]
    context = profiles.get("search_context") or {}
    if not query or not similar:
        raise ValueError("비교할 두 투수의 프로필이 필요합니다.")

    input_fb = query.get("primary_fastball") or {}
    similar_fb = similar.get("primary_fastball") or {}
    input_name = str(query.get("player_name", "검색 투수"))
    similar_name = str(similar.get("player_name", "비교 투수"))
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

    recommendations = []
    for index, target in enumerate((profiles.get("transfer_targets") or [])[:2], start=1):
        shape = target.get("target_shape") or {}
        pieces = [f"비교 투수의 {target.get('pitch_name') or target.get('pitch_type')} 표본 구사율은 {target.get('source_usage_pct', '—')}%입니다."]
        if shape.get("velo_mph") is not None:
            pieces.append(f"검색 투수의 주 패스트볼에 상대 구종 차이를 적용한 참고 목표 구속은 {float(shape['velo_mph']):.1f} mph입니다.")
        recommendations.append({
            "rank": index,
            "pitch_type": target.get("pitch_type"),
            "pitch_name": target.get("pitch_name"),
            "action": "비교 관찰",
            "confidence": "해당 없음",
            "rationale": pieces,
            "usage_plan": "실제 구종 변경·효과는 이 데이터만으로 판단할 수 없습니다.",
        })

    return {
        "model": "Statcast 수치 기반 설명 (AI 생성 아님)",
        "source": "rule_based",
        "created_at": datetime.now(timezone.utc).date().isoformat(),
        "response": {
            "summary": summary,
            "fastball_comparison": {"similarities": similarities, "differences": differences},
            "recommendations": recommendations,
        },
        "validation_warnings": ["외부 AI 키가 없어 검증 가능한 수치 비교만 제공했습니다."],
    }
