from __future__ import annotations

from typing import Any, Optional

from vtsql.config import COLUMN_RANGES


def clamp_int_optional(val: Any, low: int, high: int) -> Optional[int]:
    if val is None:
        return None
    try:
        return max(low, min(high, int(float(val))))
    except (TypeError, ValueError):
        return None


def default_filter_state() -> dict[str, Any]:
    t_lo, t_hi = COLUMN_RANGES["temperature"]
    h_lo, h_hi = COLUMN_RANGES["humidity"]
    r_lo, r_hi = COLUMN_RANGES["range_metric"]
    return {
        "cities": [],
        "temperature_min": t_lo,
        "temperature_max": t_hi,
        "humidity_min": h_lo,
        "humidity_max": h_hi,
        "range_min": r_lo,
        "range_max": r_hi,
    }


def resolve_filter_state(parsed: dict[str, Any]) -> dict[str, Any]:
    """Turn LLM extraction JSON into concrete slider-equivalent bounds."""
    t_lo, t_hi = COLUMN_RANGES["temperature"]
    h_lo, h_hi = COLUMN_RANGES["humidity"]
    r_lo, r_hi = COLUMN_RANGES["range_metric"]
    cities = [str(c).strip() for c in (parsed.get("cities") or []) if c is not None and str(c).strip()]
    return {
        "cities": cities,
        "temperature_min": clamp_int_optional(parsed.get("temperature_min"), t_lo, t_hi) or t_lo,
        "temperature_max": clamp_int_optional(parsed.get("temperature_max"), t_lo, t_hi) or t_hi,
        "humidity_min": clamp_int_optional(parsed.get("humidity_min"), h_lo, h_hi) or h_lo,
        "humidity_max": clamp_int_optional(parsed.get("humidity_max"), h_lo, h_hi) or h_hi,
        "range_min": clamp_int_optional(parsed.get("range_min"), r_lo, r_hi) or r_lo,
        "range_max": clamp_int_optional(parsed.get("range_max"), r_lo, r_hi) or r_hi,
    }


def merge_filter_delta(previous: dict[str, Any] | None, parsed: dict[str, Any]) -> dict[str, Any]:
    return resolve_filter_state(parsed)
