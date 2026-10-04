"""Region router: scores regions, picks the best one per call, and compares against naive routing.

Permanent logic. Scores and water math come from scoring.py, region constants from regions.py.
- /complete uses choose_region(): winner-take-all, the best-scoring region for this call.
- /route returns the softmax split for N calls (planning view) plus savings vs. naive.
"""
from datetime import datetime, timezone

from . import scoring
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


def route(req: RouteRequest, at: datetime | None = None) -> RouteResponse:
    at = at or datetime.now(timezone.utc)
    regions = REGIONS[req.provider]
    grids = [scoring.grid_at(r, at) for r in regions]          # same cascade for carbon and water
    carbon = [g["gco2_per_kwh"] for g in grids]
    shares = _normalize(scoring.raw_shares(regions, carbon, req.weights, at))

    kwh = req.num_calls * KWH_PER_CALL
    naive_i = next(i for i, r in enumerate(regions) if r.name == DEFAULT_REGION[req.provider])
    naive = scoring.water_breakdown(kwh, regions[naive_i], at)
    naive_co2 = kwh * carbon[naive_i]

    routed = [scoring.water_breakdown(s * kwh, r, at) for s, r in zip(shares, regions)]
    routed_co2 = sum(s * kwh * c for s, c in zip(shares, carbon))
    routed_water = sum(b["water_l"] for b in routed)
    routed_stress = sum(b["stress_weighted_l"] for b in routed)
    per_kwh = [scoring.water_breakdown(1.0, r, at) for r in regions]

    return RouteResponse(
        distribution=[
            RegionShare(
                region=r.name, share=s, grid_carbon_gco2_kwh=round(c, 1),
                water_stress_score=r.water_stress_score, lat=r.lat, lon=r.lon,
                grid_source=g["source"], site_stress=round(b["site_stress"], 3),
                stress_weighted_l_per_kwh=round(b["stress_weighted_l"], 4),
            )
            for r, s, c, g, b in zip(regions, shares, carbon, grids, per_kwh)
        ],
        naive_baseline=NaiveBaseline(
            region=regions[naive_i].name, co2_g=round(naive_co2, 2),
            water_l=round(naive["water_l"], 2), water_stress_l=round(naive["stress_weighted_l"], 2),
        ),
        routed_totals=Totals(co2_g=round(routed_co2, 2), water_l=round(routed_water, 2),
                             water_stress_l=round(routed_stress, 2)),
        savings=Savings(
            co2_g=round(naive_co2 - routed_co2, 2),
            water_l=round(naive["water_l"] - routed_water, 2),
            pct_co2=_pct_saved(naive_co2, routed_co2),
            pct_water=_pct_saved(naive["water_l"], routed_water),
            water_stress_l=round(naive["stress_weighted_l"] - routed_stress, 2),
            pct_water_stress=_pct_saved(naive["stress_weighted_l"], routed_stress),
        ),
    )


def choose_region(weights: Weights, provider: str = "azure") -> str:
    """Pick one region for a single call: the best-scoring one (largest share). Winner-take-all."""
    dist = route(RouteRequest(provider=provider, num_calls=1, weights=weights)).distribution
    return max(dist, key=lambda d: d.share).region