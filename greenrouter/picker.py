"""Model picker.

Scorer: NVIDIA prompt-task-and-complexity-classifier, using its constraint_ct
sub-score with a single cutoff. 0.70 was picked from a cutoff table on 42
hand-labeled prompts (~3 of 12 hard prompts went to the small model, ~4 of 30
easy ones to the big model). Only "simple" and "complex" are returned;
"medium" was not validated, so it is never produced.

The signature of pick_model is unchanged, so main.py doesn't change.
"""
from datetime import datetime, timezone

from . import scoring
from .nvidia_model import nvidia_scores
from .regions import DEFAULT_REGION, KWH_PER_CALL, REGIONS
from .schemas import EstimatedSavings, PickModelRequest, PickModelResponse

LARGE_CUTOFF = 0.70

DEFAULT_MODEL = "gpt-5-mini"    # what naive routing uses for every prompt
SMALL_MODEL = "gpt-4.1-mini"    # what simple prompts get downgraded to

# PLACEHOLDER, owned by the stats teammate: SMALL_MODEL's energy per call as a
# fraction of DEFAULT_MODEL's (KWH_PER_CALL). 0.2 reproduces the old placeholder
# (2.4 Wh saved out of 3 Wh). Replace with a cited ratio.
SMALL_MODEL_ENERGY_FACTOR = 0.2


def score_prompt(text: str) -> float:
    """Swap this out if the scorer changes."""
    return nvidia_scores([text])["constraint_ct"][0]


def _estimate_savings(downgraded: bool, provider: str = "azure") -> EstimatedSavings:
    """Per-call savings from using the small model, valued in the naive
    (default) region so it matches /route's baseline."""
    kwh_saved = KWH_PER_CALL * (1 - SMALL_MODEL_ENERGY_FACTOR) if downgraded else 0.0
    region = next(r for r in REGIONS[provider] if r.name == DEFAULT_REGION[provider])
    carbon = scoring.grid_at(region, datetime.now(timezone.utc))["gco2_per_kwh"]  # same source as /route
    return EstimatedSavings(
        energy_wh=round(kwh_saved * 1000, 3),
        co2_g=round(kwh_saved * carbon, 3),
        water_ml=round(scoring.water_l(kwh_saved, region) * 1000, 3),
    )


def pick_model(req: PickModelRequest) -> PickModelResponse:
    complexity = "complex" if score_prompt(req.prompt) >= LARGE_CUTOFF else "simple"
    downgraded = complexity == "simple"
    return PickModelResponse(
        complexity=complexity,
        recommended_model=SMALL_MODEL if downgraded else DEFAULT_MODEL,
        default_model=DEFAULT_MODEL,
        estimated_savings=_estimate_savings(downgraded),
    )