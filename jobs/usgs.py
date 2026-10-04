"""Shared USGS helpers for load_water.py and load_plants.py.

Watershed lookup: USGS Watershed Boundary Dataset map service (point in polygon).
Stress data: USGS National Water Availability Assessment, monthly by HUC12, water years
2010-2020. Download the WIDE csv for each variable from:
  https://water.usgs.gov/nwaa-data/data-file-directory?path=data/integrated-water-availability/iwa-assessment-outputs-conus-2025/<var>/
  <var> = consum, strflow (and optionally sui).  Save under data/usgs/ (gitignored).

Or use the single combined file (all variables, long format):
  combined_iwa-assessment-outputs-conus-2025_historical_CONUS_200910-202009_long.csv
  -> pass it with --combined instead of --consum/--strflow/--sui.

Stress = consumptive use / streamflow per month, clipped to [0, 1], averaged by calendar
month -> 12 values per HUC12. Per the model README, the pipeline accumulates and routes
the water balance through the HUC12 network, so both terms include everything upstream:
the ratio at a HUC12 is the share of upstream supply consumed above that point.
"""
import pandas as pd
import requests

WBD = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/{layer}/query"
LAYER = {"huc8": 4, "huc12": 6}  # VERIFY in the service's layer list if lookups return nothing


def lookup_huc(lat: float, lon: float, level: str) -> str | None:
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": level,
        "returnGeometry": "false", "f": "json",
    }
    r = requests.get(WBD.format(layer=LAYER[level]), params=params, timeout=30)
    r.raise_for_status()
    feats = r.json().get("features", [])
    return str(feats[0]["attributes"][level]).zfill(int(level[3:])) if feats else None


def _norm(code: str) -> str:
    return str(code).strip().zfill(12)


def read_monthly(path: str, huc12s: list[str]) -> pd.DataFrame:
    """Read only the requested HUC12 columns from a large wide csv.
    Returns rows = records, index = calendar month (1-12), columns = 12-digit HUC12."""
    header = pd.read_csv(path, nrows=0).columns
    wanted = {_norm(h) for h in huc12s}
    cols = {c: _norm(c) for c in header if c != "year_month" and _norm(c) in wanted}
    missing = wanted - set(cols.values())
    if missing:
        print(f"[usgs] not found in {path}: {sorted(missing)}")
    df = pd.read_csv(path, usecols=["year_month", *cols], dtype={"year_month": str}).rename(columns=cols)
    df["month"] = df["year_month"].str.replace(r"\D", "", regex=True).str[-2:].astype(int)
    return df.drop(columns="year_month").set_index("month").astype(float)


def monthly_stress(consum_csv: str, strflow_csv: str, huc12s: list[str]) -> pd.DataFrame:
    """12 x n table: index month 1-12, columns HUC12, values stress in [0, 1]."""
    consum = read_monthly(consum_csv, huc12s)
    flow = read_monthly(strflow_csv, huc12s)
    ratio = (consum / flow.where(flow > 0)).clip(0, 1)
    # No flow at all = fully stressed (matches the USGS SUI convention for 0/0)
    return ratio.groupby(level=0).mean().fillna(1.0)


def monthly_mean(csv: str, huc12s: list[str]) -> pd.DataFrame:
    """Calendar-month mean of any variable (used for sui cross-check)."""
    return read_monthly(csv, huc12s).groupby(level=0).mean()


def read_combined(path: str, huc12s: list[str], chunksize: int = 2_000_000) -> pd.DataFrame:
    """Stream the large combined long csv, keeping only the requested HUC12s.
    Returns columns: huc12, month, consum, strflow, sui (units suffixes stripped)."""
    wanted = {_norm(h) for h in huc12s}
    keep = []
    for chunk in pd.read_csv(path, dtype={"huc12_id": str, "year_month": str}, chunksize=chunksize):
        chunk["huc12"] = chunk["huc12_id"].map(_norm)
        hit = chunk[chunk["huc12"].isin(wanted)]
        if not hit.empty:
            keep.append(hit)
    if not keep:
        raise KeyError(f"None of {sorted(wanted)} found in {path}")
    df = pd.concat(keep)
    rename = {}
    for var in ("consum", "strflow", "sui"):
        col = next((c for c in df.columns if c.startswith(var + "_")), None)
        if col is None:
            raise KeyError(f"No column starting with '{var}_' in {path}: {list(df.columns)}")
        rename[col] = var
    df = df.rename(columns=rename)
    df["month"] = df["year_month"].str.replace(r"\D", "", regex=True).str[-2:].astype(int)
    missing = wanted - set(df["huc12"])
    if missing:
        print(f"[usgs] not found in {path}: {sorted(missing)}")
    return df[["huc12", "month", "consum", "strflow", "sui"]]


def combined_stress(path: str, huc12s: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """From the combined file: (stress, sui), each 12 x n with index month, columns HUC12."""
    df = read_combined(path, huc12s)
    df["stress"] = (df["consum"] / df["strflow"].where(df["strflow"] > 0)).clip(0, 1)
    stress = df.pivot_table(index="month", columns="huc12", values="stress", aggfunc="mean").fillna(1.0)
    sui = df.pivot_table(index="month", columns="huc12", values="sui", aggfunc="mean")
    return stress, sui