"""Poll EIA-930 hourly generation by fuel type, compute per region and hour:
  gco2_per_kwh            = sum(fuel share x emission factor)
  gen_water_l_per_kwh     = sum(fuel share x water factor)                  (physical, off-site)
  sw_gen_water_l_per_kwh  = sum(fuel share x water factor x fuel's basin stress for the month)
and upsert into TigerData (table: grid_intensity).

Fuel basin stress comes from fuel_stress (jobs/load_plants.py). Fuels without a value fall
back to the region's site stress (water_stress, jobs/load_water.py). If neither is loaded,
sw_gen_water_l_per_kwh is left NULL and scoring.py falls back too.
Re-run the 365-day backfill after loading or changing stress data.

Run from the repo root:
  python -m jobs.eia_ingest --days 2 --dry-run   # test your EIA key, no DB writes
  python -m jobs.eia_ingest --days 365           # one-time backfill (seasonality)
  python -m jobs.eia_ingest --days 3             # hourly refresh; safe to re-run
Env (.env): EIA_API_KEY, TIGER_DSN
"""
import argparse
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

API = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
PAGE = 5000  # EIA v2 max rows per request

# Azure region -> EIA balancing authority. VERIFY on EIA's BA map.
REGION_BA = {
    "westus": "CISO",          # CAISO (California)
    "northcentralus": "PJM",   # Chicago area is in PJM; EIA fuel mix is PJM-wide
}

# Lifecycle gCO2e/kWh by EIA fuel code. Source: IPCC AR5 WG3 Annex III medians. VERIFY.
EMISSION_G_PER_KWH = {
    "COL": 820, "NG": 490, "NUC": 12, "SUN": 48, "WND": 11, "WAT": 24, "GEO": 38,
    "OIL": 820,  # TODO: no AR5 median; coal used as a conservative stand-in
    "OTH": 490,  # TODO: unknown mix; gas used as a stand-in
    "BAT": 0, "PS": 0,  # storage discharge; emissions counted when charged
}
# Consumptive water L/kWh by fuel. Source: Macknick et al. 2012 (NREL) medians,
# recirculating cooling, gal/MWh x 3.785 / 1000. VERIFY.
WATER_L_PER_KWH = {
    "COL": 2.60, "NG": 0.75, "NUC": 2.54, "OIL": 2.60, "SUN": 0.004, "WND": 0.0,
    "WAT": 0.0,  # reservoir evaporation excluded; state in assumptions
    "GEO": 0.0, "OTH": 0.75, "BAT": 0.0, "PS": 0.0,
}
DEFAULT_G, DEFAULT_W = 490, 0.75


def fetch_fuel_mix(api_key: str, ba: str, start: datetime, end: datetime) -> list[dict]:
    rows, offset = [], 0
    while True:
        params = {
            "api_key": api_key, "frequency": "hourly", "data[0]": "value",
            "facets[respondent][]": ba,
            "start": start.strftime("%Y-%m-%dT%H"), "end": end.strftime("%Y-%m-%dT%H"),
            "sort[0][column]": "period", "sort[0][direction]": "asc",
            "offset": offset, "length": PAGE,
        }
        r = requests.get(API, params=params, timeout=60)
        r.raise_for_status()
        batch = r.json()["response"]["data"]
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def to_hourly(rows: list[dict], fuel_stress: dict | None = None,
              site_stress: dict | None = None) -> list[tuple]:
    """Fuel rows -> [(ts_utc, gco2, gen_water, total_mwh, sw_gen_water_or_None)] per hour.
    fuel_stress: {(fuel, month): stress}; site_stress: {month: stress}."""
    by_hour = defaultdict(dict)
    for row in rows:
        if row.get("value") is None:
            continue
        by_hour[row["period"]][row["fueltype"]] = max(float(row["value"]), 0.0)  # drop storage charging

    out = []
    for period, mix in sorted(by_hour.items()):
        total = sum(mix.values())
        if total <= 0:
            continue
        g = sum(m * EMISSION_G_PER_KWH.get(f, DEFAULT_G) for f, m in mix.items()) / total
        w = sum(m * WATER_L_PER_KWH.get(f, DEFAULT_W) for f, m in mix.items()) / total
        ts = datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        out.append((ts, g, w, total, _stress_weighted(mix, total, ts.month, fuel_stress, site_stress)))
    return out


def _stress_weighted(mix: dict, total: float, month: int,
                     fuel_stress: dict | None, site_stress: dict | None) -> float | None:
    """Per-fuel hourly mix weighting: each fuel's water is weighted by its own plants' basins."""
    fuel_stress, site_stress = fuel_stress or {}, site_stress or {}
    sw = 0.0
    for fuel, mwh in mix.items():
        water = WATER_L_PER_KWH.get(fuel, DEFAULT_W)
        if water == 0:
            continue  # solar/wind/hydro/storage: no consumptive water, stress irrelevant
        s = fuel_stress.get((fuel, month), site_stress.get(month))
        if s is None:
            return None  # stress not loaded yet
        sw += mwh * water * s
    return sw / total


def load_stress(conn, region: str) -> tuple[dict, dict]:
    fuel = {(f, m): s for f, m, s in conn.execute(
        "SELECT fuel, month, stress FROM fuel_stress WHERE region = %s", (region,)).fetchall()}
    site = {m: s for m, s in conn.execute(
        "SELECT month, stress FROM water_stress WHERE region = %s", (region,)).fetchall()}
    return fuel, site


UPSERT = """
INSERT INTO grid_intensity (ts, region, ba, gco2_per_kwh, gen_water_l_per_kwh, total_mwh,
                            sw_gen_water_l_per_kwh)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ts, region) DO UPDATE SET
  gco2_per_kwh = EXCLUDED.gco2_per_kwh,
  gen_water_l_per_kwh = EXCLUDED.gen_water_l_per_kwh,
  total_mwh = EXCLUDED.total_mwh,
  sw_gen_water_l_per_kwh = EXCLUDED.sw_gen_water_l_per_kwh
"""


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--dry-run", action="store_true", help="fetch and print, no DB writes")
    args = p.parse_args()

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    conn = None
    if not args.dry_run:
        import psycopg
        conn = psycopg.connect(os.environ["TIGER_DSN"])

    try:
        for region, ba in REGION_BA.items():
            fuel_s, site_s = load_stress(conn, region) if conn else ({}, {})
            hourly = to_hourly(fetch_fuel_mix(os.environ["EIA_API_KEY"], ba, start, end), fuel_s, site_s)
            if hourly:
                ts, g, w, _, sw = hourly[-1]
                sw_txt = f"{sw:.2f}" if sw is not None else "n/a (stress not loaded)"
                print(f"{region} ({ba}): {len(hourly)} hours | latest {ts:%Y-%m-%d %H}:00 UTC "
                      f"| {g:.0f} gCO2/kWh | {w:.2f} L/kWh | stress-weighted {sw_txt} | lag {end - ts}")
            else:
                print(f"{region} ({ba}): no data returned")
            if conn:
                with conn.cursor() as cur:
                    cur.executemany(UPSERT, [(ts, region, ba, g, w, t, sw) for ts, g, w, t, sw in hourly])
        if conn:
            conn.execute("REFRESH MATERIALIZED VIEW typical_hourly")
            conn.commit()
            print("Upserted to TigerData and refreshed typical_hourly.")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()