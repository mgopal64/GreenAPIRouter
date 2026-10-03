"""Region router: splits calls across regions and compares against naive routing.

Permanent logic. The split itself comes from scoring.py and the numbers from regions.py.
"""
import random

from . import grid, scoring
from .regions import DEFAULT_REGION, KWH_PER_CALL, REGIONS
from .schemas import NaiveBaseline, RegionShare, RouteRequest, RouteResponse, Savings, Totals, Weights


def _normalize(raw: list[float], digits: int = 4) -> list[float]:
    """Scale to sum to 1, round, and put any rounding remainder on the largest share so the total is exact."""
    total = sum(raw)
    shares = [round(x / total, digits) for x in raw] if total > 0 else [round(1 / len(raw), digits)] * len(raw)
    biggest = shares.index(max(shares))
    shares[biggest] = round(shares[biggest] + 1 - sum(shares), digits)
    return shares


def _pct_saved(naive: float, routed: float) -> float:
    return round(100 * (1 - routed / naive), 1) if naive else 0.0


def route(req: RouteRequest) -> RouteResponse:
    regions = REGIONS[req.provider]
    carbon = [grid.carbon(r.name, r.grid_carbon_gco2_kwh) for r in regions]
    shares = _normalize(scoring.raw_shares(regions, carbon, req.weights))

    kwh = req.num_calls * KWH_PER_CALL
    naive_i = next(i for i, r in enumerate(regions) if r.name == DEFAULT_REGION[req.provider])
    naive_co2 = kwh * carbon[naive_i]
    naive_water = scoring.water_l(kwh, regions[naive_i])
    routed_co2 = sum(s * kwh * c for s, c in zip(shares, carbon))
    routed_water = sum(scoring.water_l(s * kwh, r) for s, r in zip(shares, regions))

    return RouteResponse(
        distribution=[
            RegionShare(
                region=r.name, share=s, grid_carbon_gco2_kwh=c,
                water_stress_score=r.water_stress_score, lat=r.lat, lon=r.lon,
            )
            for r, s, c in zip(regions, shares, carbon)
        ],
        naive_baseline=NaiveBaseline(
            region=regions[naive_i].name, co2_g=round(naive_co2, 2), water_l=round(naive_water, 2)
        ),
        routed_totals=Totals(co2_g=round(routed_co2, 2), water_l=round(routed_water, 2)),
        savings=Savings(
            co2_g=round(naive_co2 - routed_co2, 2),
            water_l=round(naive_water - routed_water, 2),
            pct_co2=_pct_saved(naive_co2, routed_co2),
            pct_water=_pct_saved(naive_water, routed_water),
        ),
    )


def choose_region(weights: Weights, provider: str = "azure") -> str:
    """Pick one region for a single call, sampled from the routed distribution."""
    dist = route(RouteRequest(provider=provider, num_calls=1, weights=weights)).distribution
    return random.choices([d.region for d in dist], weights=[d.share for d in dist])[0]
