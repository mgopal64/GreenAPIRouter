"""How traffic is split across regions and how water impact is measured.

Data flow for one scoring call at UTC time `at`:
  carbon (gCO2/kWh)        -> passed in by router.py; grid.py should use grid_at() below
  generation water (L/kWh) -> grid_at(): live -> recent (6h) -> yesterday -> typical -> static
  watershed stress (0-1)   -> TigerData water_stress for that month (USGS consumption / supply)
  on-site cooling water    -> per-site WUE and PUE (SITE below; move into regions.py once cited)

Signatures are unchanged for router.py; `at` is optional and defaults to now (UTC).
If TigerData is unreachable, everything falls back to the static values in regions.py
so the demo never crashes.
"""
import math
import os
import time
from datetime import datetime, timedelta, timezone

from .regions import WATER_L_PER_KWH, Region
from .schemas import Weights

try:
    import psycopg
except ImportError:  # lets the module import without the driver installed
    psycopg = None

DSN = os.environ.get("TIGER_DSN")
CACHE_TTL_S = 300      # re-read TigerData at most every 5 minutes per key
LIVE_WINDOW_H = 6      # step 2 of the grid_at cascade: newest hour within this window
TEMPERATURE = 0.15     # lower = more traffic to the single best region

# TODO (stats owner): replace with cited per-region values (Microsoft datacenter fact sheets).
SITE = {
    "westus": {"pue": 1.2, "wue_l_per_kwh": 0.3},
    "northcentralus": {"pue": 1.2, "wue_l_per_kwh": 0.3},
}

_cache: dict = {}


# ---------- TigerData access (cached, with fallback) ----------

def _query_one(key, sql, params):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    row = None
    if psycopg and DSN:
        try:
            with psycopg.connect(DSN, connect_timeout=3) as conn:
                row = conn.execute(sql, params).fetchone()
        except Exception as e:  # DB down: fall back, don't break routing
            print(f"[scoring] TigerData unavailable ({e.__class__.__name__}); using fallback")
    _cache[key] = (time.time(), row)
    return row


def _hour(at: datetime) -> datetime:
    return at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def grid_at(region: Region, at: datetime) -> dict:
    """Carbon and generation water for `region` at hour `at`, cascading:
    1. live: exact hour  2. recent: newest within 6h  3. yesterday: same hour -24h
    4. typical: median for this month + UTC hour over the past year  5. static fallback
    """
    h = _hour(at)
    cols = "gco2_per_kwh, gen_water_l_per_kwh"
    steps = [
        ("live", f"SELECT {cols} FROM grid_intensity WHERE region = %s AND ts = %s",
         (region.name, h)),
        ("recent", f"""SELECT {cols} FROM grid_intensity
                       WHERE region = %s AND ts < %s AND ts >= %s
                       ORDER BY ts DESC LIMIT 1""",
         (region.name, h, h - timedelta(hours=LIVE_WINDOW_H))),
        ("yesterday", f"SELECT {cols} FROM grid_intensity WHERE region = %s AND ts = %s",
         (region.name, h - timedelta(hours=24))),
        ("typical", f"SELECT {cols} FROM typical_hourly WHERE region = %s AND month = %s AND hour_utc = %s",
         (region.name, h.month, h.hour)),
    ]
    for source, sql, params in steps:
        row = _query_one((source, region.name, h), sql, params)
        if row:
            return {"gco2_per_kwh": row[0], "gen_water_l_per_kwh": row[1], "source": source}
    return {"gco2_per_kwh": region.grid_carbon_gco2_kwh,
            "gen_water_l_per_kwh": WATER_L_PER_KWH, "source": "static"}


def gen_water_l_per_kwh(region: Region, at: datetime) -> float:
    """Off-site water consumed to generate 1 kWh in this region's grid at hour `at`."""
    return grid_at(region, at)["gen_water_l_per_kwh"]


def stress(region: Region, at: datetime) -> float:
    """Watershed stress 0-1 for the month of `at` (USGS consumption / supply)."""
    row = _query_one(
        ("stress", region.name, at.month),
        "SELECT stress FROM water_stress WHERE region = %s AND month = %s",
        (region.name, at.month),
    )
    return row[0] if row else region.water_stress_score / 5  # Aqueduct 0-5 -> 0-1


# ---------- Impact functions ----------

def water_intensity_l_per_kwh(region: Region, at: datetime) -> float:
    """Physical liters per kWh of facility energy: on-site cooling + off-site generation."""
    site = SITE.get(region.name, {"pue": 1.2, "wue_l_per_kwh": 0.3})
    onsite = site["wue_l_per_kwh"] / site["pue"]   # WUE is per kWh of IT energy
    return onsite + gen_water_l_per_kwh(region, at)


def water_l(kwh: float, region: Region, at: datetime | None = None) -> float:
    """Physical water in liters for `kwh` of facility energy in `region`. No stress weighting."""
    at = at or datetime.now(timezone.utc)
    return kwh * water_intensity_l_per_kwh(region, at)


def stress_weighted_water_l(kwh: float, region: Region, at: datetime | None = None) -> float:
    """Water impact: physical liters x watershed stress. This is what routing minimizes."""
    at = at or datetime.now(timezone.utc)
    return water_l(kwh, region, at) * stress(region, at)


def raw_shares(regions: list[Region], carbon: list[float], weights: Weights,
               at: datetime | None = None) -> list[float]:
    """Relative share of traffic per region (router normalizes them).

    `carbon` is each region's gCO2/kWh at `at`, same order as `regions`.
    """
    at = at or datetime.now(timezone.utc)
    water = [water_intensity_l_per_kwh(r, at) * stress(r, at) for r in regions]

    # Normalize each metric to 0-1 across regions so the weights are comparable.
    max_c, max_w = max(carbon) or 1.0, max(water) or 1.0
    total_w = (weights.carbon + weights.water) or 1.0
    wc, ww = weights.carbon / total_w, weights.water / total_w
    scores = [wc * c / max_c + ww * w / max_w for c, w in zip(carbon, water)]

    # Softmax over negative score: best region gets most traffic, others keep some.
    best = min(scores)
    return [math.exp(-(s - best) / TEMPERATURE) for s in scores]