from __future__ import annotations

from typing import Any, Optional

from vtsql.config import COLUMN_RANGES


def bounds_if_narrow(global_lo: int, global_hi: int, sel_min: int, sel_max: int) -> Optional[tuple[int, int]]:
    if sel_min <= global_lo and sel_max >= global_hi:
        return None
    lo = max(sel_min, global_lo)
    hi = min(sel_max, global_hi)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def build_sql_and_params(
    cities_selected: list[str],
    temp_min: int,
    temp_max: int,
    hum_min: int,
    hum_max: int,
    range_min_val: int,
    range_max_val: int,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []

    if cities_selected:
        city_clauses = []
        for city in cities_selected:
            city_clauses.append("city ILIKE %s")
            params.append(city.strip())
        clauses.append("(" + " OR ".join(city_clauses) + ")")

    t_bounds = bounds_if_narrow(*COLUMN_RANGES["temperature"], temp_min, temp_max)
    if t_bounds:
        clauses.append("temperature BETWEEN %s AND %s")
        params.extend(t_bounds)

    h_bounds = bounds_if_narrow(*COLUMN_RANGES["humidity"], hum_min, hum_max)
    if h_bounds:
        clauses.append("humidity BETWEEN %s AND %s")
        params.extend(h_bounds)

    r_bounds = bounds_if_narrow(*COLUMN_RANGES["range_metric"], range_min_val, range_max_val)
    if r_bounds:
        clauses.append('"range" BETWEEN %s AND %s')
        params.extend(r_bounds)

    where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT id, city, temperature, humidity, \"range\"\n"
        "FROM city_metrics\n"
        f"{where_clause}\n"
        "ORDER BY city, id"
    )
    return sql, tuple(params)


def normalized_filter_debug(
    cities_selected: list[str],
    temp_min: int,
    temp_max: int,
    hum_min: int,
    hum_max: int,
    range_min_val: int,
    range_max_val: int,
) -> dict[str, Any]:
    t_bounds = bounds_if_narrow(*COLUMN_RANGES["temperature"], temp_min, temp_max)
    h_bounds = bounds_if_narrow(*COLUMN_RANGES["humidity"], hum_min, hum_max)
    r_bounds = bounds_if_narrow(*COLUMN_RANGES["range_metric"], range_min_val, range_max_val)
    return {
        "cities": cities_selected,
        "temperature_min": t_bounds[0] if t_bounds else COLUMN_RANGES["temperature"][0],
        "temperature_max": t_bounds[1] if t_bounds else COLUMN_RANGES["temperature"][1],
        "humidity_min": h_bounds[0] if h_bounds else COLUMN_RANGES["humidity"][0],
        "humidity_max": h_bounds[1] if h_bounds else COLUMN_RANGES["humidity"][1],
        "range_min": r_bounds[0] if r_bounds else COLUMN_RANGES["range_metric"][0],
        "range_max": r_bounds[1] if r_bounds else COLUMN_RANGES["range_metric"][1],
        "narrow_temperature": bool(t_bounds),
        "narrow_humidity": bool(h_bounds),
        "narrow_range": bool(r_bounds),
        "city_filter_disabled": not bool(cities_selected),
    }
