"""Site (direct-water) watershed stress for each Azure region -> TigerData water_stress.

Uses lat/lon from greenrouter/regions.py, finds the HUC8 + HUC12 by point in polygon,
then computes monthly stress = consumption / streamflow from USGS (see jobs/usgs.py).

Run from the repo root:
  python -m jobs.load_water --lookup          # just print each region's HUC8/HUC12
  python -m jobs.load_water --combined data/usgs/combined_..._long.csv
  (or: --consum ..._wide.csv --strflow ..._wide.csv [--sui ..._wide.csv])
Env: TIGER_DSN
"""
import argparse
import os

from dotenv import load_dotenv

from greenrouter.regions import REGIONS
from jobs.usgs import combined_stress, lookup_huc, monthly_mean, monthly_stress

UPSERT = """
INSERT INTO water_stress (region, month, huc12, huc8, stress, sui) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (region, month) DO UPDATE SET huc12 = EXCLUDED.huc12, huc8 = EXCLUDED.huc8,
  stress = EXCLUDED.stress, sui = EXCLUDED.sui
"""


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--lookup", action="store_true")
    p.add_argument("--combined", help="combined long csv with all variables")
    p.add_argument("--consum"); p.add_argument("--strflow"); p.add_argument("--sui")
    a = p.parse_args()

    sites = {}
    for r in REGIONS["azure"]:
        sites[r.name] = (lookup_huc(r.lat, r.lon, "huc8"), lookup_huc(r.lat, r.lon, "huc12"))
        print(f"{r.name} ({r.lat}, {r.lon}) -> huc8 {sites[r.name][0]}, huc12 {sites[r.name][1]}")
    if a.lookup:
        return

    huc12s = [h12 for _, h12 in sites.values() if h12]
    if a.combined:
        stress, sui = combined_stress(a.combined, huc12s)
    else:
        stress = monthly_stress(a.consum, a.strflow, huc12s)
        sui = monthly_mean(a.sui, huc12s) if a.sui else None

    import psycopg
    with psycopg.connect(os.environ["TIGER_DSN"]) as conn, conn.cursor() as cur:
        for region, (h8, h12) in sites.items():
            if not h12 or h12 not in stress.columns:
                print(f"{region}: no stress data for HUC12 {h12}; skipped"); continue
            for month in range(1, 13):
                s = float(stress.at[month, h12])
                u = float(sui.at[month, h12]) if sui is not None and h12 in sui.columns else None
                cur.execute(UPSERT, (region, month, h12, h8, s, u))
            print(f"{region}: stress by month {stress[h12].round(2).tolist()}")
        conn.commit()


if __name__ == "__main__":
    main()