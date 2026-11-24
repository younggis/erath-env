"""Wind conventions.

u = eastward component, v = northward component (m/s).
speed = hypot(u, v).
Meteorological direction is the direction the wind comes FROM:
    direction = (atan2(-u, -v) * 180/pi + 360) % 360
UI particles should point along the wind TO vector (u, v); text labels report
the meteorological FROM direction. Both are always provided together.
"""
from __future__ import annotations

import math


def wind_speed(u: float, v: float) -> float:
    return math.hypot(u, v)


def wind_direction_from(u: float, v: float, calm_threshold: float = 0.1) -> float | None:
    """Meteorological 'from' direction in degrees; None for calm."""
    if wind_speed(u, v) < calm_threshold:
        return None
    return (math.atan2(-u, -v) * 180.0 / math.pi + 360.0) % 360.0


def wind_to_vector(u: float, v: float) -> tuple[float, float]:
    """Unit 'to' direction (east, north); (0,0) for calm."""
    s = wind_speed(u, v)
    if s == 0:
        return 0.0, 0.0
    return u / s, v / s


def compass(direction: float | None) -> str:
    if direction is None:
        return "静风"
    names = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    idx = int((direction + 22.5) % 360 // 45)
    return names[idx]


def describe_wind(u: float | None, v: float | None) -> dict:
    if u is None or v is None:
        return {"speed_ms": None, "direction_from_deg": None, "compass": None, "to_east": None, "to_north": None}
    te, tn = wind_to_vector(u, v)
    d = wind_direction_from(u, v)
    return {
        "speed_ms": round(wind_speed(u, v), 3),
        "direction_from_deg": None if d is None else round(d, 1),
        "compass": compass(d),
        "to_east": round(te, 5),
        "to_north": round(tn, 5),
    }
