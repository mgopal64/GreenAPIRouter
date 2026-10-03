"""How traffic is split across regions and how water impact is measured.

PLACEHOLDER LOGIC — owned by the stats teammate. Replace the bodies of these two
functions; keep the signatures so router.py doesn't change.
"""
from .regions import WATER_L_PER_KWH, Region
from .schemas import Weights


def raw_shares(regions: list[Region], carbon: list[float], weights: Weights) -> list[float]:
    """Relative share of traffic per region (any positive numbers; the router normalizes them).

    `carbon` is each region's current gCO2/kWh (live or fallback), in the same order as `regions`.
    """
    # Placeholder: lower combined score = greener = more traffic. Real version: e.g. softmax over top-k.
    scores = [weights.carbon * c / 400 + weights.water * r.water_stress_score / 5 for r, c in zip(regions, carbon)]
    return [1 / (s + 1e-6) for s in scores]


def water_l(kwh: float, region: Region) -> float:
    """Water impact in liters for `kwh` of compute in `region`."""
    # Placeholder: inflates liters by watershed stress, which isn't physically right.
    # The stats teammate should define this (e.g. per-site WUE, or report stress-weighted water separately).
    return kwh * WATER_L_PER_KWH * (1 + region.water_stress_score / 5)
