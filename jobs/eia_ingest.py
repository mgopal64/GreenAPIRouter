"""Poll EIA-930 hourly generation by fuel type, compute gCO2/kWh and generation water
per kWh for each region, and upsert into TigerData (table: grid_intensity).

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


def to_hourly(rows: list[dict]) -> list[tuple]:
    """Fuel rows -> [(ts_utc, gco2_per_kwh, gen_water_l_per_kwh, total_mwh)] per hour."""
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
        out.append((ts, g, w, total))
    return out


UPSERT = """
INSERT INTO grid_intensity (ts, region, ba, gco2_per_kwh, gen_water_l_per_kwh, total_mwh)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (ts, region) DO UPDATE SET
  gco2_per_kwh = EXCLUDED.gco2_per_kwh,
  gen_water_l_per_kwh = EXCLUDED.gen_water_l_per_kwh,
  total_mwh = EXCLUDED.total_mwh
"""


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--dry-run", action="store_true", help="fetch and print, no DB writes")
    args = p.parse_args()

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    results = {}
    for region, ba in REGION_BA.items():
        hourly = to_hourly(fetch_fuel_mix(os.environ["EIA_API_KEY"], ba, start, end))
        results[region] = (ba, hourly)
        if hourly:
            ts, g, w, _ = hourly[-1]
            print(f"{region} ({ba}): {len(hourly)} hours | latest {ts:%Y-%m-%d %H}:00 UTC "
                  f"| {g:.0f} gCO2/kWh | {w:.2f} L/kWh | lag {end - ts}")
        else:
            print(f"{region} ({ba}): no data returned")

    if args.dry_run:
        return

    import psycopg
    with psycopg.connect(os.environ["TIGER_DSN"]) as conn:
        with conn.cursor() as cur:
            for region, (ba, hourly) in results.items():
                cur.executemany(UPSERT, [(ts, region, ba, g, w, t) for ts, g, w, t in hourly])
        conn.execute("REFRESH MATERIALIZED VIEW typical_hourly")
        conn.commit()
    print("Upserted to TigerData and refreshed typical_hourly.")


if __name__ == "__main__":
    main()