"""Statcast 투구 데이터를 3차원 궤적으로 복원한다.

Baseball Savant CSV의 ``vx0``, ``vy0``, ``vz0``, ``ax``, ``ay``, ``az``는
홈 플레이트 뒤쪽 꼭짓점에서 50 ft 떨어진 지점을 기준으로 한 운동 파라미터다.
이 모듈은 해당 파라미터를 우선 사용해 다음의 Statcast 운동식을 계산한다.

    position(t) = position(0) + velocity(0) * t + acceleration * t**2 / 2

CSV에는 50 ft 지점의 x/z 위치가 없으므로 ``plate_x``와 ``plate_z``에서
역산한다. 원본 운동 파라미터가 없는 집계 데이터는 릴리스/도착 위치와
``pfx_x``, ``pfx_z``를 이용한 endpoint-constrained 보조 모델로 복원한다.

좌표계
------
``statcast``
    x는 포수 시점의 좌우, y는 홈 플레이트 뒤쪽 꼭짓점으로부터의 거리,
    z는 지면으로부터의 높이이며 단위는 모두 ft다.
``threejs``
    참고 ``Pitch3D.tsx``와 호환되도록 ``(-x, z, y - plate_y)``로 변환한다.
    즉 반환 필드 x/y/z는 각각 화면의 좌우/높이/깊이다.

이 계산은 공개 CSV의 상수 가속도 근사치를 재현하는 것이며 Hawk-Eye의 원본
프레임별 추적 데이터를 새로 추정하는 공기역학 시뮬레이터는 아니다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite, sqrt
from typing import Literal, TypedDict


FT_PER_MPH = 5280.0 / 3600.0
MPH_PER_FT_PER_SECOND = 1.0 / FT_PER_MPH
STATCAST_REFERENCE_Y_FT = 50.0
HOME_PLATE_FRONT_Y_FT = 17.0 / 12.0
HOME_PLATE_MIDDLE_Y_FT = 17.0 / 24.0
PITCHING_RUBBER_Y_FT = 60.5
GRAVITY_FT_PER_SECOND_SQUARED = 32.174

_KINEMATIC_FIELDS = ("vx0", "vy0", "vz0", "ax", "ay", "az")

CoordinateSystem = Literal["statcast", "threejs"]
TrajectoryMethod = Literal["auto", "statcast", "movement"]
PfxUnit = Literal["feet", "inches"]


class TrajectoryPoint(TypedDict):
    """한 시점의 공 위치와 속력."""

    x: float
    y: float
    z: float
    time: float
    speed_mph: float


class TrajectoryResult(TypedDict):
    """직렬화 가능한 궤적 계산 결과."""

    method: str
    coordinate_system: str
    flight_time: float
    plate_y: float
    release_error_ft: dict[str, float] | None
    points: list[TrajectoryPoint]


class TrajectoryError(ValueError):
    """입력값으로 유효한 투구 궤적을 만들 수 없을 때 발생한다."""


def reconstruct_pitch_trajectory(
    pitch: Mapping[str, object],
    *,
    samples: int = 61,
    method: TrajectoryMethod = "auto",
    coordinate_system: CoordinateSystem = "statcast",
    pfx_unit: PfxUnit = "feet",
    plate_y: float | None = None,
    precision: int | None = 4,
) -> TrajectoryResult:
    """단일 Statcast 투구 행 또는 구종 집계값을 3D 궤적으로 복원한다.

    Parameters
    ----------
    pitch:
        pandas ``Series``를 포함한 mapping 형태의 투구 데이터. 실제 투구에는
        Statcast의 6개 운동 파라미터와 ``plate_x``, ``plate_z``가 필요하다.
        movement 보조 모델에는 ``release_speed``, 릴리스 위치, 플레이트 위치,
        ``pfx_x``, ``pfx_z``가 필요하다.
    samples:
        릴리스와 플레이트 지점을 포함한 반환 점 개수(최소 2).
    method:
        ``auto``는 운동 파라미터가 모두 유효하면 ``statcast``, 아니면
        ``movement``를 선택한다.
    coordinate_system:
        원본 Statcast 좌표 또는 Three.js 렌더링 좌표.
    pfx_unit:
        movement 보조 모델의 pfx 단위. Baseball Savant CSV는 ``feet``다.
    plate_y:
        홈 플레이트 교차 지점. 생략하면 ``game_year``가 2026 이상일 때
        플레이트 중앙(17/24 ft), 그 이전은 앞면(17/12 ft)을 사용한다.
    precision:
        JSON 크기를 줄이기 위한 반올림 자릿수. ``None``이면 반올림하지 않는다.

    Returns
    -------
    dict
        선택된 방법, 비행 시간, 진단값 및 ``points``를 담은 JSON 호환 dict.

    Notes
    -----
    ``release_error_ft``는 Statcast 다항식이 보고된 릴리스 위치와 얼마나 다른지
    보여주는 진단값이다. 플레이트 위치와 공개 운동 파라미터를 보존하기 위해
    궤적 자체를 임의로 휘어 이 오차를 숨기지 않는다.
    """

    if samples < 2:
        raise TrajectoryError("samples는 릴리스/도착점을 위해 2 이상이어야 합니다.")
    if method not in ("auto", "statcast", "movement"):
        raise TrajectoryError(f"지원하지 않는 method입니다: {method!r}")
    if coordinate_system not in ("statcast", "threejs"):
        raise TrajectoryError(
            f"지원하지 않는 coordinate_system입니다: {coordinate_system!r}"
        )
    if pfx_unit not in ("feet", "inches"):
        raise TrajectoryError(f"지원하지 않는 pfx_unit입니다: {pfx_unit!r}")

    resolved_plate_y = _resolve_plate_y(pitch, plate_y)
    has_kinematics = all(
        _optional_number(pitch, name) is not None for name in _KINEMATIC_FIELDS
    )
    selected_method = "statcast" if method == "auto" and has_kinematics else method
    if selected_method == "auto":
        selected_method = "movement"

    if selected_method == "statcast":
        if not has_kinematics:
            missing = [
                name
                for name in _KINEMATIC_FIELDS
                if _optional_number(pitch, name) is None
            ]
            raise TrajectoryError(
                "Statcast 복원에 필요한 값이 없습니다: " + ", ".join(missing)
            )
        result = _reconstruct_from_statcast(
            pitch, samples=samples, plate_y=resolved_plate_y
        )
    else:
        result = _reconstruct_from_movement(
            pitch,
            samples=samples,
            plate_y=resolved_plate_y,
            pfx_unit=pfx_unit,
        )

    if coordinate_system == "threejs":
        result["points"] = to_threejs_points(result["points"], resolved_plate_y)
        result["coordinate_system"] = "threejs"

    if precision is not None:
        if precision < 0:
            raise TrajectoryError("precision은 0 이상의 정수 또는 None이어야 합니다.")
        result = _round_result(result, precision)
    return result


def reconstruct_many(
    pitches: Iterable[Mapping[str, object]], **kwargs: object
) -> list[TrajectoryResult]:
    """여러 투구를 동일 옵션으로 복원한다."""

    return [reconstruct_pitch_trajectory(pitch, **kwargs) for pitch in pitches]


def to_threejs_points(
    points: Iterable[TrajectoryPoint], plate_y: float
) -> list[TrajectoryPoint]:
    """Statcast 좌표를 참고 ``Pitch3D.tsx``의 Three.js 좌표로 변환한다.

    포수 시점의 Statcast x를 화면 x축에 맞게 반전하고, Statcast z를 Three.js의
    수직 y축으로 옮긴다. 깊이는 홈 플레이트 교차 지점이 0이 되도록 정규화한다.
    """

    return [
        TrajectoryPoint(
            x=-point["x"],
            y=point["z"],
            z=point["y"] - plate_y,
            time=point["time"],
            speed_mph=point["speed_mph"],
        )
        for point in points
    ]


def _reconstruct_from_statcast(
    pitch: Mapping[str, object], *, samples: int, plate_y: float
) -> TrajectoryResult:
    vx0 = _required_number(pitch, "vx0")
    vy0 = _required_number(pitch, "vy0")
    vz0 = _required_number(pitch, "vz0")
    ax = _required_number(pitch, "ax")
    ay = _required_number(pitch, "ay")
    az = _required_number(pitch, "az")
    plate_x = _required_number(pitch, "plate_x")
    plate_z = _required_number(pitch, "plate_z")
    release_y = _release_y(pitch)

    if vy0 >= 0:
        raise TrajectoryError("vy0는 홈 방향 투구에서 음수여야 합니다.")
    if release_y <= STATCAST_REFERENCE_Y_FT:
        raise TrajectoryError("release_pos_y는 Statcast 기준점인 50 ft보다 커야 합니다.")
    if plate_y >= STATCAST_REFERENCE_Y_FT:
        raise TrajectoryError("plate_y는 Statcast 기준점인 50 ft보다 작아야 합니다.")

    release_t = _time_at_y(release_y, vy0, ay)
    plate_t = _time_at_y(plate_y, vy0, ay)
    if not release_t < 0 < plate_t:
        raise TrajectoryError("릴리스부터 홈 플레이트까지의 비행 시간을 계산할 수 없습니다.")

    # CSV는 x0/z0를 노출하지 않으므로 측정 plate_x/plate_z에서 역산한다.
    x_at_50 = plate_x - vx0 * plate_t - 0.5 * ax * plate_t * plate_t
    z_at_50 = plate_z - vz0 * plate_t - 0.5 * az * plate_t * plate_t

    points: list[TrajectoryPoint] = []
    flight_time = plate_t - release_t
    for index in range(samples):
        fraction = index / (samples - 1)
        t = release_t + flight_time * fraction
        x = _position(x_at_50, vx0, ax, t)
        y = _position(STATCAST_REFERENCE_Y_FT, vy0, ay, t)
        z = _position(z_at_50, vz0, az, t)
        speed = _speed(vx0 + ax * t, vy0 + ay * t, vz0 + az * t)
        points.append(
            TrajectoryPoint(
                x=x,
                y=y,
                z=z,
                time=t - release_t,
                speed_mph=speed * MPH_PER_FT_PER_SECOND,
            )
        )

    # 부동소수점 오차 없이 공개된 플레이트 측정값을 그대로 보존한다.
    points[-1]["x"] = plate_x
    points[-1]["y"] = plate_y
    points[-1]["z"] = plate_z

    reported_release_x = _optional_number(pitch, "release_pos_x")
    reported_release_z = _optional_number(pitch, "release_pos_z")
    release_error = None
    if reported_release_x is not None or reported_release_z is not None:
        release_error = {}
        if reported_release_x is not None:
            release_error["x"] = points[0]["x"] - reported_release_x
        if reported_release_z is not None:
            release_error["z"] = points[0]["z"] - reported_release_z

    return TrajectoryResult(
        method="statcast",
        coordinate_system="statcast",
        flight_time=flight_time,
        plate_y=plate_y,
        release_error_ft=release_error,
        points=points,
    )


def _reconstruct_from_movement(
    pitch: Mapping[str, object],
    *,
    samples: int,
    plate_y: float,
    pfx_unit: PfxUnit,
) -> TrajectoryResult:
    release_speed = _required_number(pitch, "release_speed")
    release_x = _required_number(pitch, "release_pos_x")
    release_z = _required_number(pitch, "release_pos_z")
    release_y = _release_y(pitch)
    plate_x = _required_number(pitch, "plate_x")
    plate_z = _required_number(pitch, "plate_z")
    pfx_x = _required_number(pitch, "pfx_x")
    pfx_z = _required_number(pitch, "pfx_z")

    if release_speed <= 0:
        raise TrajectoryError("release_speed는 0보다 커야 합니다.")
    if release_y <= plate_y:
        raise TrajectoryError("release_pos_y는 plate_y보다 커야 합니다.")
    if pfx_unit == "inches":
        pfx_x /= 12.0
        pfx_z /= 12.0

    initial_speed = release_speed * FT_PER_MPH
    distance = release_y - plate_y
    # 공개 운동 파라미터가 없을 때만 쓰는 근사치다. MLB 투구의 일반적인
    # 비행 중 감속을 반영해 평균 전진 속도를 릴리스 속도의 94%로 둔다.
    flight_time = distance / (initial_speed * 0.94)
    vy = -initial_speed
    ay = 2.0 * (-distance - vy * flight_time) / (flight_time * flight_time)
    ax = 2.0 * pfx_x / (flight_time * flight_time)
    az = -GRAVITY_FT_PER_SECOND_SQUARED + 2.0 * pfx_z / (
        flight_time * flight_time
    )
    vx = (plate_x - release_x - 0.5 * ax * flight_time**2) / flight_time
    vz = (plate_z - release_z - 0.5 * az * flight_time**2) / flight_time

    points: list[TrajectoryPoint] = []
    for index in range(samples):
        t = flight_time * index / (samples - 1)
        points.append(
            TrajectoryPoint(
                x=_position(release_x, vx, ax, t),
                y=_position(release_y, vy, ay, t),
                z=_position(release_z, vz, az, t),
                time=t,
                speed_mph=_speed(vx + ax * t, vy + ay * t, vz + az * t)
                * MPH_PER_FT_PER_SECOND,
            )
        )

    points[0].update(x=release_x, y=release_y, z=release_z)
    points[-1].update(x=plate_x, y=plate_y, z=plate_z)
    return TrajectoryResult(
        method="movement",
        coordinate_system="statcast",
        flight_time=flight_time,
        plate_y=plate_y,
        release_error_ft=None,
        points=points,
    )


def _resolve_plate_y(pitch: Mapping[str, object], plate_y: float | None) -> float:
    if plate_y is not None:
        value = _finite_float(plate_y, "plate_y")
        if value < 0:
            raise TrajectoryError("plate_y는 0 이상이어야 합니다.")
        return value
    year = _optional_number(pitch, "game_year")
    if year is not None and year >= 2026:
        return HOME_PLATE_MIDDLE_Y_FT
    return HOME_PLATE_FRONT_Y_FT


def _release_y(pitch: Mapping[str, object]) -> float:
    release_y = _optional_number(pitch, "release_pos_y")
    if release_y is not None:
        return release_y
    extension = _optional_number(pitch, "release_extension")
    if extension is None:
        raise TrajectoryError(
            "release_pos_y 또는 이를 계산할 release_extension 값이 필요합니다."
        )
    return PITCHING_RUBBER_Y_FT - extension


def _time_at_y(target_y: float, vy0: float, ay: float) -> float:
    displacement = STATCAST_REFERENCE_Y_FT - target_y
    if abs(ay) < 1e-12:
        return -displacement / vy0

    discriminant = vy0 * vy0 - 2.0 * ay * displacement
    if discriminant < 0:
        raise TrajectoryError(
            f"y={target_y:g} ft에서 실수 시간 해가 없습니다(discriminant < 0)."
        )
    root = sqrt(discriminant)
    roots = ((-vy0 - root) / ay, (-vy0 + root) / ay)
    if target_y > STATCAST_REFERENCE_Y_FT:
        candidates = [value for value in roots if value < 0]
        if candidates:
            return max(candidates)
    else:
        candidates = [value for value in roots if value >= 0]
        if candidates:
            return min(candidates)
    raise TrajectoryError(f"y={target_y:g} ft에 도달하는 물리적인 시간 해가 없습니다.")


def _position(
    position0: float, velocity0: float, acceleration: float, time: float
) -> float:
    return position0 + velocity0 * time + 0.5 * acceleration * time * time


def _speed(vx: float, vy: float, vz: float) -> float:
    return sqrt(vx * vx + vy * vy + vz * vz)


def _required_number(pitch: Mapping[str, object], name: str) -> float:
    value = _optional_number(pitch, name)
    if value is None:
        raise TrajectoryError(f"유효한 {name} 값이 필요합니다.")
    return value


def _optional_number(pitch: Mapping[str, object], name: str) -> float | None:
    try:
        raw_value = pitch[name]
    except (KeyError, TypeError):
        return None
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise TrajectoryError(f"{name}은 유한한 숫자여야 합니다.")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TrajectoryError(f"{name}은 유한한 숫자여야 합니다.") from error
    if not isfinite(result):
        raise TrajectoryError(f"{name}은 유한한 숫자여야 합니다.")
    return result


def _round_result(result: TrajectoryResult, precision: int) -> TrajectoryResult:
    result["flight_time"] = round(result["flight_time"], precision)
    result["plate_y"] = round(result["plate_y"], precision)
    if result["release_error_ft"] is not None:
        result["release_error_ft"] = {
            axis: round(value, precision)
            for axis, value in result["release_error_ft"].items()
        }
    for point in result["points"]:
        for key in ("x", "y", "z", "time", "speed_mph"):
            point[key] = round(point[key], precision)
    return result


__all__ = [
    "TrajectoryError",
    "TrajectoryPoint",
    "TrajectoryResult",
    "reconstruct_many",
    "reconstruct_pitch_trajectory",
    "to_threejs_points",
]
