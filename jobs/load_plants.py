"""Per-fuel watershed stress for each grid (indirect water) -> TigerData fuel_stress.

For each balancing authority, take the top N plants by capacity for each water-consuming
fuel (gas combined cycle, coal, nuclear), find each plant's HUC12, compute its monthly
stress, and store the capacity-weighted mean per fuel per month.

Data: EIA-860 annual (https://www.eia.gov/electricity/data/eia860/). From the latest zip,
use 2___Plant_Y<year>.xlsx and 3_1_Generator_Y<year>.xlsx. Save under data/eia860/.

Run from the repo root (after load_water.py, before the eia_ingest backfill):
  python -m jobs.load_plants --plants data/eia860/2___Plant_Y2024.xlsx \
      --generators data/eia860/3_1_Generator_Y2024.xlsx \
      --combined data/usgs/combined_..._long.csv   (or --consum/--strflow wide files)
  add --dry-run to print the chosen plants without touching the database.
Env: TIGER_DSN
"""
import argparse
import os

import pandas as pd
from dotenv import load_dotenv

from jobs.eia_ingest import REGION_BA
from jobs.usgs import combined_stress, lookup_huc, monthly_stress

COAL_CODES = {"BIT", "SUB", "LIG", "RC", "ANT", "WC", "SGC"}
GAS_COMBINED_CYCLE = {"CA", "CS", "CT"}  # baseload gas; simple-cycle peakers (GT) excluded

# Plants cooled with seawater (once-through ocean cooling) draw no freshwater, so their
# basin stress is 0. They stay in the capacity weighting so the seawater share counts.
# Add names here if the dry-run list shows other coastal plants. Matching is by substring.
SEAWATER_COOLED = ("Diablo Canyon", "Moss Landing")


def _seawater(name: str) -> bool:
    return any(k.lower() in str(name).lower() for k in SEAWATER_COOLED)


def _read_eia860(path: str, sheet: str | int = 0) -> pd.DataFrame:
    """EIA-860 sheets have a title row above the header; find the row with 'Plant Code'."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=5)
    header_row = next(i for i in range(5) if "Plant Code" in raw.iloc[i].astype(str).tolist())
    return pd.read_excel(path, sheet_name=sheet, header=header_row)


def classify(row) -> str | None:
    src, pm = str(row["Energy Source 1"]).strip(), str(row["Prime Mover"]).strip()
    if src == "NUC":
        return "NUC"
    if src in COAL_CODES:
        return "COL"
    if src == "NG" and pm in GAS_COMBINED_CYCLE:
        return "NG"
    return None


def top_plants(plants_xlsx: str, gens_xlsx: str, top_n: int) -> pd.DataFrame:
    plants = _read_eia860(plants_xlsx)[
        ["Plant Code", "Plant Name", "Latitude", "Longitude", "Balancing Authority Code"]]
    gens = _read_eia860(gens_xlsx)[
        ["Plant Code", "Energy Source 1", "Prime Mover", "Nameplate Capacity (MW)"]]
    gens["fuel"] = gens.apply(classify, axis=1)
    gens = gens.dropna(subset=["fuel"])
    gens["Nameplate Capacity (MW)"] = pd.to_numeric(gens["Nameplate Capacity (MW)"], errors="coerce")

    cap = gens.groupby(["Plant Code", "fuel"], as_index=False)["Nameplate Capacity (MW)"].sum()
    df = cap.merge(plants, on="Plant Code")
    ba_to_region = {ba: region for region, ba in REGION_BA.items()}
    df = df[df["Balancing Authority Code"].isin(ba_to_region)]
    df["region"] = df["Balancing Authority Code"].map(ba_to_region)
    df = (df.sort_values("Nameplate Capacity (MW)", ascending=False)
            .groupby(["region", "fuel"]).head(top_n).reset_index(drop=True))
    return df.rename(columns={"Plant Code": "plant_id", "Plant Name": "name", "Latitude": "lat",
                              "Longitude": "lon", "Balancing Authority Code": "ba",
                              "Nameplate Capacity (MW)": "capacity_mw"})


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--plants", required=True); p.add_argument("--generators", required=True)
    p.add_argument("--combined"); p.add_argument("--consum"); p.add_argument("--strflow")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    df = top_plants(a.plants, a.generators, a.top)
    df["huc8"] = [lookup_huc(la, lo, "huc8") for la, lo in zip(df.lat, df.lon)]
    df["huc12"] = [lookup_huc(la, lo, "huc12") for la, lo in zip(df.lat, df.lon)]
    df["cooling"] = df["name"].map(lambda n: "seawater" if _seawater(n) else "freshwater")
    print(df[["region", "fuel", "name", "capacity_mw", "huc12", "cooling"]].to_string(index=False))
    if a.dry_run:
        return

    huc12s = df["huc12"].dropna().unique().tolist()
    stress = (combined_stress(a.combined, huc12s)[0] if a.combined
              else monthly_stress(a.consum, a.strflow, huc12s))
    rows = []
    for (region, fuel), g in df.groupby(["region", "fuel"]):
        g = g[g["huc12"].isin(stress.columns) | g["name"].map(_seawater)]
        if g.empty:
            print(f"{region} {fuel}: no plants with stress data; scoring will fall back to site stress")
            continue
        w = g["capacity_mw"] / g["capacity_mw"].sum()
        for month in range(1, 13):
            plant_s = [0.0 if _seawater(n) else float(stress.at[month, h])
                       for n, h in zip(g["name"], g["huc12"])]
            s = float((pd.Series(plant_s, index=g.index) * w).sum())
            rows.append((region, fuel, month, s, len(g)))
        print(f"{region} {fuel}: {len(g)} plants, annual mean stress "
              f"{sum(r[3] for r in rows[-12:]) / 12:.2f}")

    import psycopg
    with psycopg.connect(os.environ["TIGER_DSN"]) as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO power_plants (plant_id, region, ba, fuel, name, lat, lon, capacity_mw, huc8, huc12)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (plant_id, fuel) DO UPDATE SET capacity_mw = EXCLUDED.capacity_mw,
                 huc8 = EXCLUDED.huc8, huc12 = EXCLUDED.huc12""",
            [(int(r.plant_id), r.region, r.ba, r.fuel, r.name, float(r.lat), float(r.lon),
              float(r.capacity_mw), r.huc8, r.huc12) for r in df.itertuples()])
        cur.executemany(
            """INSERT INTO fuel_stress (region, fuel, month, stress, n_plants) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (region, fuel, month) DO UPDATE SET stress = EXCLUDED.stress,
                 n_plants = EXCLUDED.n_plants""", rows)
        conn.commit()
    print("Wrote power_plants and fuel_stress. Now re-run: python -m jobs.eia_ingest --days 365")


if __name__ == "__main__":
    main()