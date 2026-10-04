"""Per-call impact accounting: energy, CO2, water, stress-weighted water, cost.

Called by /complete after Azure responds, using the REAL token counts from `usage`:
  IT energy (kWh)       = prompt_tokens x Wh/1K in + completion_tokens x Wh/1K out   (model)
  facility energy (kWh) = IT energy x PUE                                            (region)
  CO2, water, stress    = facility energy x the region's intensities at that hour    (scoring.py)
Baseline = what naive routing would have done: the large model in DEFAULT_REGION, same tokens.
(completion_tokens already includes gpt-5-mini reasoning tokens; don't add them again.)

Logging to TigerData happens on a background thread and never blocks or breaks a request.
"""
import os
import threading
from datetime import datetime, timezone

from . import scoring
from .regions import DEFAULT_REGION, REGIONS

# TODO (stats owner): replace with cited values (e.g. Jegham et al. 2025, "How Hungry is AI?").
# Wh of IT energy per 1K tokens, and list price USD per 1M tokens (VERIFY Azure Global Standard prices).
MODEL_ENERGY = {
    "gpt-4.1-mini": {"wh_per_1k_in": 0.02, "wh_per_1k_out": 0.20, "usd_per_1m_in": 0.40, "usd_per_1m_out": 1.60},
    "gpt-5-mini":   {"wh_per_1k_in": 0.03, "wh_per_1k_out": 0.30, "usd_per_1m_in": 0.25, "usd_per_1m_out": 2.00},
}
DEFAULT_MODEL_ENERGY = MODEL_ENERGY["gpt-5-mini"]
BASELINE_DEPLOYMENT = os.environ.get("LARGE_DEPLOYMENT", "gpt-5-mini")


def _region(name: str):
    return next(r for regions in REGIONS.values() for r in regions if r.name == name)


def impact(deployment: str, region_name: str, prompt_tokens: int, completion_tokens: int,
           at: datetime | None = None) -> dict:
    """Impact of one call in `region_name` on `deployment` at time `at`."""
    at = at or datetime.now(timezone.utc)
    m = MODEL_ENERGY.get(deployment, DEFAULT_MODEL_ENERGY)
    region = _region(region_name)
    site = scoring.SITE.get(region_name, scoring.DEFAULT_SITE)

    it_kwh = (prompt_tokens / 1000 * m["wh_per_1k_in"] + completion_tokens / 1000 * m["wh_per_1k_out"]) / 1000
    kwh = it_kwh * site["pue"]
    grid = scoring.grid_at(region, at)
    water = scoring.water_breakdown(kwh, region, at)

    return {
        "energy_wh": kwh * 1000,
        "co2_g": kwh * grid["gco2_per_kwh"],
        "water_ml": water["water_l"] * 1000,
        "water_stress_ml": water["stress_weighted_l"] * 1000,
        "cost_usd": prompt_tokens / 1e6 * m["usd_per_1m_in"] + completion_tokens / 1e6 * m["usd_per_1m_out"],
        "grid_source": grid["source"],
    }


def _pct(base: float, actual: float) -> float:
    return round(100 * (1 - actual / base), 1) if base else 0.0


def account(deployment: str, region_name: str, prompt_tokens: int, completion_tokens: int,
            at: datetime | None = None) -> dict:
    """Actual vs. naive baseline for one call, plus % saved."""
    at = at or datetime.now(timezone.utc)
    actual = impact(deployment, region_name, prompt_tokens, completion_tokens, at)
    base_region = DEFAULT_REGION["azure"]
    baseline = impact(BASELINE_DEPLOYMENT, base_region, prompt_tokens, completion_tokens, at)
    return {
        "actual": actual,
        "baseline": {**baseline, "deployment": BASELINE_DEPLOYMENT, "region": base_region},
        "pct_saved": {k: _pct(baseline[k], actual[k])
                      for k in ("energy_wh", "co2_g", "water_ml", "water_stress_ml", "cost_usd")},
    }


_INSERT = """
INSERT INTO calls (ts, complexity, deployment, region, prompt_tokens, completion_tokens, latency_ms,
  grid_source, energy_wh, co2_g, water_ml, water_stress_ml, cost_usd,
  base_deployment, base_region, base_energy_wh, base_co2_g, base_water_ml, base_water_stress_ml,
  base_cost_usd, prompt_preview)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _write(row: tuple):
    if not (scoring.psycopg and scoring.DSN):
        return
    try:
        with scoring.psycopg.connect(scoring.DSN, connect_timeout=3) as conn:
            conn.execute(_INSERT, row)
    except Exception as e:  # logging must never break a request
        print(f"[accounting] log failed ({e.__class__.__name__}: {e})")


def account_and_log(*, prompt: str, complexity: str, deployment: str, region: str,
                    prompt_tokens: int, completion_tokens: int, latency_ms: int | None = None,
                    at: datetime | None = None) -> dict:
    """Compute impact and log it to TigerData in the background. Returns the account dict."""
    at = at or datetime.now(timezone.utc)
    acc = account(deployment, region, prompt_tokens, completion_tokens, at)
    a, b = acc["actual"], acc["baseline"]
    row = (at, complexity, deployment, region, prompt_tokens, completion_tokens, latency_ms,
           a["grid_source"], a["energy_wh"], a["co2_g"], a["water_ml"], a["water_stress_ml"], a["cost_usd"],
           b["deployment"], b["region"], b["energy_wh"], b["co2_g"], b["water_ml"], b["water_stress_ml"],
           b["cost_usd"], prompt[:80])
    threading.Thread(target=_write, args=(row,), daemon=True).start()
    return acc


def to_schema(acc: dict):
    """Convert account() output to the CompleteImpact response model."""
    from .schemas import CallImpact, CompleteImpact
    keys = ("energy_wh", "co2_g", "water_ml", "water_stress_ml", "cost_usd")
    r = lambda d: CallImpact(**{k: round(d[k], 6) for k in keys})
    return CompleteImpact(actual=r(acc["actual"]), baseline=r(acc["baseline"]),
                          baseline_deployment=acc["baseline"]["deployment"],
                          baseline_region=acc["baseline"]["region"],
                          pct_saved=acc["pct_saved"], grid_source=acc["actual"]["grid_source"])