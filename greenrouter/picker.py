"""Model picker.

Scorer: NVIDIA prompt-task-and-complexity-classifier, using its constraint_ct
sub-score with a single cutoff. 0.70 was picked from a cutoff table on 42
hand-labeled prompts (~3 of 12 hard prompts went to the small model, ~4 of 30
easy ones to the big model). Only "simple" and "complex" are returned;
"medium" was not validated, so it is never produced.

The signature of pick_model is unchanged, so main.py doesn't change.
"""
from . import accounting, tokens
from .nvidia_model import nvidia_scores
from .regions import DEFAULT_REGION
from .schemas import EstimatedSavings, PickModelRequest, PickModelResponse, TokenEstimate

LARGE_CUTOFF = 0.70

DEFAULT_MODEL = "gpt-5-mini"    # what naive routing uses for every prompt
SMALL_MODEL = "gpt-4.1-mini"    # what simple prompts get downgraded to

def score_prompt(text: str) -> float:
    """Swap this out if the scorer changes."""
    return nvidia_scores([text])["constraint_ct"][0]


def _estimate_savings(est: TokenEstimate, downgraded: bool, provider: str = "azure") -> EstimatedSavings:
    """Per-call savings from using the small model instead of the default one, for the estimated
    tokens, valued in the naive (default) region. Same formula as live calls (accounting.impact),
    so the estimate and the real result after /complete are directly comparable."""
    if not downgraded:
        return EstimatedSavings(energy_wh=0.0, co2_g=0.0, water_ml=0.0)
    region = DEFAULT_REGION[provider]
    big = accounting.impact(DEFAULT_MODEL, region, est.prompt_tokens, est.completion_tokens)
    small = accounting.impact(SMALL_MODEL, region, est.prompt_tokens, est.completion_tokens)
    return EstimatedSavings(
        energy_wh=round(big["energy_wh"] - small["energy_wh"], 4),
        co2_g=round(big["co2_g"] - small["co2_g"], 4),
        water_ml=round(big["water_ml"] - small["water_ml"], 4),
    )


def pick_model(req: PickModelRequest) -> PickModelResponse:
    complexity = "complex" if score_prompt(req.prompt) >= LARGE_CUTOFF else "simple"
    downgraded = complexity == "simple"
    est = TokenEstimate(
        prompt_tokens=tokens.prompt_tokens(req.prompt), completion_tokens=tokens.output_tokens(complexity)
    )
    return PickModelResponse(
        complexity=complexity,
        recommended_model=SMALL_MODEL if downgraded else DEFAULT_MODEL,
        default_model=DEFAULT_MODEL,
        estimated_savings=_estimate_savings(est, downgraded),
        token_estimate=est,
    )