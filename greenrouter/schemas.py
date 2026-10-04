"""Pydantic models mirroring the v1 API contract in CLAUDE.md."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    # Reject unknown fields and NaN/Infinity instead of silently accepting them.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# --- /pick-model ---

class PickModelRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    user_preference: float = Field(0.5, ge=0, le=1)  # 0 = max eco, 0.5 = default, 1 = max conservative
    simplification_mode: Literal["none", "structural"] = "structural"


class EstimatedSavings(BaseModel):
    energy_wh: float
    co2_g: float
    water_ml: float


class TokenEstimate(BaseModel):
    prompt_tokens: int  # approximate count of the prompt
    completion_tokens: int  # assumed typical answer length for this complexity


class PickModelResponse(BaseModel):
    complexity: Literal["simple", "medium", "complex"]
    recommended_model: str
    default_model: str
    estimated_savings: EstimatedSavings  # per call, from token_estimate via accounting.impact()
    token_estimate: TokenEstimate | None = None


# --- /route ---

class Weights(StrictModel):
    carbon: float = Field(0.5, ge=0, le=1)
    water: float = Field(0.5, ge=0, le=1)


class RouteRequest(StrictModel):
    provider: Literal["azure"] = "azure"
    num_calls: int = Field(1000, gt=0, le=10_000_000)
    weights: Weights = Weights()


class RegionShare(BaseModel):
    region: str
    share: float
    grid_carbon_gco2_kwh: float
    water_stress_score: float
    lat: float
    lon: float
    # Added (backward compatible): where the grid number came from and the water split
    grid_source: str = "static"            # live | recent | yesterday | typical | static
    site_stress: float = 0.0               # 0-1, data center watershed this month
    stress_weighted_l_per_kwh: float = 0.0


class NaiveBaseline(BaseModel):
    region: str
    co2_g: float
    water_l: float                          # physical: direct + indirect
    water_stress_l: float = 0.0             # stress-weighted impact


class Totals(BaseModel):
    co2_g: float
    water_l: float
    water_stress_l: float = 0.0


class Savings(BaseModel):
    co2_g: float
    water_l: float
    pct_co2: float
    pct_water: float
    water_stress_l: float = 0.0
    pct_water_stress: float = 0.0


class RouteResponse(BaseModel):
    distribution: list[RegionShare]
    naive_baseline: NaiveBaseline
    routed_totals: Totals
    savings: Savings


# --- /complete ---

class CompleteRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    weights: Weights = Weights()
    user_preference: float = Field(0.5, ge=0, le=1)  # 0 = max eco, 0.5 = default, 1 = max conservative
    simplification_mode: Literal["none", "structural"] = "structural"


class CallImpact(BaseModel):
    energy_wh: float
    co2_g: float
    water_ml: float                 # physical: direct + indirect
    water_stress_ml: float          # stress-weighted impact
    cost_usd: float


class CompleteImpact(BaseModel):
    actual: CallImpact
    baseline: CallImpact            # large model in the default region, same tokens
    baseline_deployment: str
    baseline_region: str
    pct_saved: dict[str, float]
    grid_source: str                # live | recent | yesterday | typical | static


class CompleteResponse(BaseModel):
    complexity: Literal["simple", "medium", "complex"]
    deployment: str
    region: str
    output: str
    prompt_tokens: int
    completion_tokens: int
    impact: CompleteImpact | None = None   # added; None if accounting failed