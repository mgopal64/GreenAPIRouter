"""Region data and impact factors.

PLACEHOLDER NUMBERS — owned by the stats teammate. Replace the values here with cited
figures; the structure is what the router depends on.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    grid_carbon_gco2_kwh: float  # static fallback; live values come from grid.py
    water_stress_score: float  # 0-5 (WRI Aqueduct scale)
    lat: float
    lon: float


REGIONS: dict[str, list[Region]] = {
    "azure": [
        # The two regions with real deployments (see azure_client.py).
        Region("westus", 220.0, 4.0, 37.78, -122.42),
        Region("northcentralus", 420.0, 1.5, 41.88, -87.63),
    ],
}

# Where naive routing sends every call.
DEFAULT_REGION = {"azure": "northcentralus"}

KWH_PER_CALL = 0.003
WATER_L_PER_KWH = 1.8


def region_names() -> list[str]:
    return [r.name for regions in REGIONS.values() for r in regions]
