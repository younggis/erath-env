"""Unit conversions. API/storage units areSI; display converts at the edge."""
from __future__ import annotations


def kelvin_to_c(k: float | None) -> float | None:
    return None if k is None else k - 273.15


def c_to_kelvin(c: float) -> float:
    return c + 273.15


def pa_to_hpa(pa: float | None) -> float | None:
    return None if pa is None else pa / 100.0


def meters_to_km(m: float | None) -> float | None:
    return None if m is None else m / 1000.0


def mixing_ratio_to_g_per_kg(kgkg: float | None) -> float | None:
    """kg/kg -> g/kg (cloud/condensate display)."""
    return None if kgkg is None else kgkg * 1000.0


def dewpoint_from_temp_rh(temp_c: float, rh_percent: float) -> float:
    """Magnus formula. Returned value is a derived diagnostic and must be labelled."""
    rh = max(1e-3, min(100.0, rh_percent))
    a, b = 17.27, 237.7
    gamma = math_ln(rh / 100.0) + (a * temp_c) / (b + temp_c)
    return (b * gamma) / (a - gamma)


def math_ln(x: float) -> float:
    import math

    return math.log(x)


def rh_from_temp_dewpoint(temp_c: float, dew_c: float) -> float:
    import math

    a, b = 17.27, 237.7
    es = 6.112 * math.exp((a * temp_c) / (b + temp_c))
    e = 6.112 * math.exp((a * dew_c) / (b + dew_c))
    return max(0.0, min(100.0, 100.0 * e / es))
