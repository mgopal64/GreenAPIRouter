"""Read-only data for the website: totals, region snapshot, and 24h replay.

All three read TigerData only (no Azure calls, no writes) and return {} / [] parts
instead of failing if the database is unreachable, so the site never crashes.
"""
from datetime import datetime, timezone

from . import scoring
from .regions import REGIONS


def _rows(sql: str, params: tuple = ()) -> list[tuple]:
    if not (scoring.psycopg and scoring.DSN):
        return []
    try:
        with scoring.psycopg.connect(scoring.DSN, connect_timeout=3) as conn:
            return conn.execute(sql, params).fetchall()
    except Exception as e:
        print(f"[dashboard] query failed ({e.__class__.__name__}: {e})")
        return []


def _pct(base, actual):
    return round(100 * (1 - actual / base), 1) if base else 0.0


METRICS = ("energy_wh", "co2_g", "water_ml", "water_stress_ml", "cost_usd")


def summary(hours: int = 24) -> dict:
    """Totals over the last `hours` from the calls table: actual vs. naive baseline."""
    cols = ", ".join([f"coalesce(sum({m}), 0)" for m in METRICS] +
                     [f"coalesce(sum(base_{m}), 0)" for m in METRICS])
    rows = _rows(f"SELECT count(*), {cols} FROM calls WHERE ts > now() - make_interval(hours => %s)",
                 (hours,))
    n, *vals = rows[0] if rows else (0, *[0] * (2 * len(METRICS)))
    actual = dict(zip(METRICS, (round(v, 6) for v in vals[:len(METRICS)])))
    baseline = dict(zip(METRICS, (round(v, 6) for v in vals[len(METRICS):])))

    by_region = _rows("SELECT region, count(*) FROM calls WHERE ts > now() - make_interval(hours => %s) "
                      "GROUP BY region", (hours,))
    by_model = _rows("SELECT deployment, count(*) FROM calls WHERE ts > now() - make_interval(hours => %s) "
                     "GROUP BY deployment", (hours,))
    return {
        "hours": hours,
        "calls": n,
        "actual": actual,
        "baseline": baseline,
        "saved": {m: round(baseline[m] - actual[m], 6) for m in METRICS},
        "pct_saved": {m: _pct(baseline[m], actual[m]) for m in METRICS},
        "calls_by_region": dict(by_region),
        "calls_by_model": dict(by_model),
    }


def regions() -> list[dict]:
    """Current snapshot per region for the map: carbon, water, stress, watershed, plants."""
    now = datetime.now(timezone.utc)
    out = []
    for r in REGIONS["azure"]:
        grid = scoring.grid_at(r, now)
        w = scoring.water_breakdown(1.0, r, now)  # per kWh of facility energy
        huc = _rows("SELECT huc8, huc12 FROM water_stress WHERE region = %s AND month = %s",
                    (r.name, now.month))
        plants = _rows("SELECT fuel, name, capacity_mw, lat, lon, huc12 FROM power_plants "
                       "WHERE region = %s ORDER BY fuel, capacity_mw DESC", (r.name,))
        out.append({
            "region": r.name,
            "lat": r.lat, "lon": r.lon,
            "huc8": huc[0][0] if huc else None,
            "huc12": huc[0][1] if huc else None,
            "grid_source": grid["source"],
            "gco2_per_kwh": round(grid["gco2_per_kwh"], 1),
            "site_stress": round(w["site_stress"], 3),
            "water_l_per_kwh": round(w["water_l"], 4),
            "stress_weighted_l_per_kwh": round(w["stress_weighted_l"], 4),
            "indirect_method": w["indirect_method"],
            "plants": [{"fuel": f, "name": n, "capacity_mw": c, "lat": la, "lon": lo, "huc12": h}
                       for f, n, c, la, lo, h in plants],
        })
    return out


def replay(hours: int = 24) -> dict:
    """Hourly carbon and stress-weighted water per region for the last `hours` of available
    EIA data (EIA lags ~1 day, so the window ends at the newest stored hour, not now)."""
    rows = _rows(
        """SELECT ts, region, gco2_per_kwh, gen_water_l_per_kwh, sw_gen_water_l_per_kwh
           FROM grid_intensity
           WHERE ts > (SELECT max(ts) FROM grid_intensity) - make_interval(hours => %s)
           ORDER BY ts, region""", (hours,))
    regions_by_name = {r.name: r for r in REGIONS["azure"]}
    points = []
    for ts, region, gco2, gen_w, sw_gen in rows:
        r = regions_by_name.get(region)
        if r is None:
            continue
        site = scoring.SITE.get(region, scoring.DEFAULT_SITE)
        s_site = scoring.stress(r, ts)
        direct = site["wue_l_per_kwh"] / site["pue"]           # per kWh facility energy
        indirect_sw = sw_gen if sw_gen is not None else gen_w * s_site
        points.append({
            "ts": ts.isoformat(), "region": region,
            "gco2_per_kwh": round(gco2, 1),
            "stress_weighted_l_per_kwh": round(direct * s_site + indirect_sw, 4),
        })

    # Which region wins each hour on carbon alone and on water alone (for the demo story)
    by_ts: dict[str, list[dict]] = {}
    for p in points:
        by_ts.setdefault(p["ts"], []).append(p)
    winners = [{"ts": ts,
                "carbon": min(ps, key=lambda p: p["gco2_per_kwh"])["region"],
                "water": min(ps, key=lambda p: p["stress_weighted_l_per_kwh"])["region"]}
               for ts, ps in by_ts.items() if len(ps) == len(REGIONS["azure"])]
    return {"hours": hours, "points": points, "winners": winners}