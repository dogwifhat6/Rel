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
    
    t_min = clamp_int_optional(parsed.get("temperature_min"), t_lo, t_hi)
    t_max = clamp_int_optional(parsed.get("temperature_max"), t_lo, t_hi)
    h_min = clamp_int_optional(parsed.get("humidity_min"), h_lo, h_hi)
    h_max = clamp_int_optional(parsed.get("humidity_max"), h_lo, h_hi)
    r_min = clamp_int_optional(parsed.get("range_min"), r_lo, r_hi)
    r_max = clamp_int_optional(parsed.get("range_max"), r_lo, r_hi)
    
    return {
        "cities": cities,
        "temperature_min": t_min if t_min is not None else t_lo,
        "temperature_max": t_max if t_max is not None else t_hi,
        "humidity_min": h_min if h_min is not None else h_lo,
        "humidity_max": h_max if h_max is not None else h_hi,
        "range_min": r_min if r_min is not None else r_lo,
        "range_max": r_max if r_max is not None else r_hi,
    }


def merge_filter_delta(previous: dict[str, Any] | None, parsed: dict[str, Any]) -> dict[str, Any]:
    t_lo, t_hi = COLUMN_RANGES["temperature"]
    h_lo, h_hi = COLUMN_RANGES["humidity"]
    r_lo, r_hi = COLUMN_RANGES["range_metric"]
    
    prev = previous or {}
    
    cities = parsed.get("cities")
    if cities is None:
        cities = prev.get("cities") or []
    else:
        cities = [str(c).strip() for c in cities if c is not None and str(c).strip()]
        
    t_min = clamp_int_optional(parsed.get("temperature_min"), t_lo, t_hi)
    if t_min is None:
        t_min = prev.get("temperature_min")
    if t_min is None:
        t_min = t_lo
        
    t_max = clamp_int_optional(parsed.get("temperature_max"), t_lo, t_hi)
    if t_max is None:
        t_max = prev.get("temperature_max")
    if t_max is None:
        t_max = t_hi
        
    h_min = clamp_int_optional(parsed.get("humidity_min"), h_lo, h_hi)
    if h_min is None:
        h_min = prev.get("humidity_min")
    if h_min is None:
        h_min = h_lo
        
    h_max = clamp_int_optional(parsed.get("humidity_max"), h_lo, h_hi)
    if h_max is None:
        h_max = prev.get("humidity_max")
    if h_max is None:
        h_max = h_hi
        
    r_min = clamp_int_optional(parsed.get("range_min"), r_lo, r_hi)
    if r_min is None:
        r_min = prev.get("range_min")
    if r_min is None:
        r_min = r_lo
        
    r_max = clamp_int_optional(parsed.get("range_max"), r_lo, r_hi)
    if r_max is None:
        r_max = prev.get("range_max")
    if r_max is None:
        r_max = r_hi
        
    return {
        "cities": cities,
        "temperature_min": t_min,
        "temperature_max": t_max,
        "humidity_min": h_min,
        "humidity_max": h_max,
        "range_min": r_min,
        "range_max": r_max,
    }
