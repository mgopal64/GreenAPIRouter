"""How traffic is split across regions and how water impact is measured.

Water model for `kwh` of facility energy in region r at UTC time t:
  direct   (on-site cooling)  = kwh / PUE x WUE                     -> IT energy x WUE
  indirect (power plants)     = kwh x gen_water_l_per_kwh(r, t)     -> hourly fuel mix x fuel water factors
  physical water              = direct + indirect
  stress-weighted water       = direct x S_site(r, month)
                              + kwh x sw_gen_water_l_per_kwh(r, t)  -> each fuel weighted by its own
                                                                       plants' basin stress (load_plants.py)
Grid values come from grid_at(): live -> recent (6h) -> yesterday -> typical -> static.
If TigerData is unreachable or stress isn't loaded, every step falls back so the demo never crashes.
Signatures used by router.py are unchanged; `at` is optional and defaults to now (UTC).
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
TEMPERATURE = 0.15     # lower = more traffic to the single best region (only affects /route)

# TODO (stats owner): replace with cited per-region values (Microsoft datacenter fact sheets).
SITE = {
    "westus": {"pue": 1.2, "wue_l_per_kwh": 0.3},
    "northcentralus": {"pue": 1.2, "wue_l_per_kwh": 0.3},
}
DEFAULT_SITE = {"pue": 1.2, "wue_l_per_kwh": 0.3}

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
    """Grid values for `region` at hour `at`, cascading:
    1. live: exact hour  2. recent: newest within 6h  3. yesterday: same hour -24h
    4. typical: median for this month + UTC hour over the past year  5. static fallback
    """
    h = _hour(at)
    cols = "gco2_per_kwh, gen_water_l_per_kwh, sw_gen_water_l_per_kwh"
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
            return {"gco2_per_kwh": row[0], "gen_water_l_per_kwh": row[1],
                    "sw_gen_water_l_per_kwh": row[2], "source": source}
    return {"gco2_per_kwh": region.grid_carbon_gco2_kwh, "gen_water_l_per_kwh": WATER_L_PER_KWH,
            "sw_gen_water_l_per_kwh": None, "source": "static"}


def gen_water_l_per_kwh(region: Region, at: datetime) -> float:
    """Off-site (power plant) water per kWh at hour `at`."""
    return grid_at(region, at)["gen_water_l_per_kwh"]


def stress(region: Region, at: datetime) -> float:
    """Site watershed stress 0-1 for the month of `at` (USGS consumption / supply)."""
    row = _query_one(
        ("stress", region.name, at.month),
        "SELECT stress FROM water_stress WHERE region = %s AND month = %s",
        (region.name, at.month),
    )
    return row[0] if row else region.water_stress_score / 5  # Aqueduct 0-5 -> 0-1


# ---------- Water functions ----------

def water_breakdown(kwh: float, region: Region, at: datetime | None = None) -> dict:
    """Everything the dashboard might show for `kwh` of facility energy."""
    at = at or datetime.now(timezone.utc)
    site = SITE.get(region.name, DEFAULT_SITE)
    grid = grid_at(region, at)
    s_site = stress(region, at)

    direct = kwh / site["pue"] * site["wue_l_per_kwh"]
    indirect = kwh * grid["gen_water_l_per_kwh"]
    if grid["sw_gen_water_l_per_kwh"] is not None:
        indirect_sw = kwh * grid["sw_gen_water_l_per_kwh"]   # per-fuel plant basins
        indirect_method = "plant basins by fuel"
    else:
        indirect_sw = indirect * s_site                       # fallback: site basin
        indirect_method = "site basin (fallback)"

    return {
        "direct_l": direct,
        "indirect_l": indirect,
        "water_l": direct + indirect,
        "direct_stress_l": direct * s_site,
        "indirect_stress_l": indirect_sw,
        "stress_weighted_l": direct * s_site + indirect_sw,
        "site_stress": s_site,
        "indirect_method": indirect_method,
        "grid_source": grid["source"],
    }


def water_l(kwh: float, region: Region, at: datetime | None = None) -> float:
    """Physical water in liters (direct + indirect). No stress weighting."""
    return water_breakdown(kwh, region, at)["water_l"]


def stress_weighted_water_l(kwh: float, region: Region, at: datetime | None = None) -> float:
    """Water impact: direct x site stress + indirect x plant-basin stress. Routing minimizes this."""
    return water_breakdown(kwh, region, at)["stress_weighted_l"]


def raw_shares(regions: list[Region], carbon: list[float], weights: Weights,
               at: datetime | None = None) -> list[float]:
    """Relative share of traffic per region (router normalizes them). Largest share = best region.

    `carbon` is each region's gCO2/kWh at `at`, same order as `regions`.
    """
    at = at or datetime.now(timezone.utc)
    water = [stress_weighted_water_l(1.0, r, at) for r in regions]  # per kWh

    # Normalize each metric to 0-1 across regions so the weights are comparable.
    max_c, max_w = max(carbon) or 1.0, max(water) or 1.0
    total_w = (weights.carbon + weights.water) or 1.0
    wc, ww = weights.carbon / total_w, weights.water / total_w
    scores = [wc * c / max_c + ww * w / max_w for c, w in zip(carbon, water)]

    # Softmax over negative score: best region gets the largest share.
    best = min(scores)
    return [math.exp(-(s - best) / TEMPERATURE) for s in scores]