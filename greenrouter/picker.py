"""Model picker.

Scorer: NVIDIA prompt-task-and-complexity-classifier, using its constraint_ct
sub-score against a cutoff that depends on the request's user_preference:

    preference 0.0 (max eco)          -> cutoff 0.85
    preference 0.5 (default)          -> cutoff 0.70   <- the validated cutoff
    preference 1.0 (max conservative) -> cutoff 0.30

0.70 was picked from a cutoff table on 42 hand-labeled prompts (~3 of 12 hard
prompts went to the small model, ~4 of 30 easy ones to the big model). In the
same table 0.85 sent ~8 of 12 hard prompts to the small model, so preference 0
is deliberately aggressive. Treat those counts as directional.

Whatever the preference, scores >= 0.85 are always "complex" and scores < 0.30
are always "simple". Only "simple" and "complex" are returned; "medium" was not
validated, so it is never produced.

The signature of pick_model is unchanged.
"""
import re
from datetime import datetime, timezone

from . import scoring
from .nvidia_model import nvidia_scores
from .regions import DEFAULT_REGION, KWH_PER_CALL, REGIONS
from .schemas import EstimatedSavings, PickModelRequest, PickModelResponse

# Cutoff on constraint_ct at the three anchor points of the preference slider.
ECO_CUTOFF = 0.85           # preference 0.0: large model only for very high scores
BALANCED_CUTOFF = 0.70      # preference 0.5: our validated methodology (the default)
CONSERVATIVE_CUTOFF = 0.30  # preference 1.0: large model unless the prompt is trivial

DEFAULT_MODEL = "gpt-5-mini"    # what naive routing uses for every prompt
SMALL_MODEL = "gpt-4.1-mini"    # what simple prompts get downgraded to

# PLACEHOLDER, owned by the stats teammate: SMALL_MODEL's energy per call as a
# fraction of DEFAULT_MODEL's (KWH_PER_CALL). 0.2 reproduces the old placeholder
# (2.4 Wh saved out of 3 Wh). Replace with a cited ratio.
SMALL_MODEL_ENERGY_FACTOR = 0.2


def cutoff_for(preference: float) -> float:
    """Piecewise-linear slider -> cutoff, passing through BALANCED_CUTOFF at 0.5
    so the default preference reproduces the validated behavior."""
    p = max(0.0, min(1.0, preference))
    if p <= 0.5:
        c = ECO_CUTOFF + (BALANCED_CUTOFF - ECO_CUTOFF) * (p / 0.5)
    else:
        c = BALANCED_CUTOFF + (CONSERVATIVE_CUTOFF - BALANCED_CUTOFF) * ((p - 0.5) / 0.5)
    return round(c, 3)


def simplify_prompt(text: str, mode: str = "structural") -> str:
    """Whitespace normalization for SCORING ONLY. Never send this text to a model.

    Keeps leading indentation (so code survives), collapses runs of blank lines,
    and collapses repeated spaces/tabs inside a line."""
    if mode == "none" or not text.strip():
        return text
    cleaned = text.replace("\r\n", "\n").strip()
    cleaned = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)*", "\n\n", cleaned)  # runs of blank lines -> one
    cleaned = re.sub(r"(?<=\S)[ \t]{2,}", " ", cleaned)            # mid-line space runs only
    return cleaned


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
    text = simplify_prompt(req.prompt, req.simplification_mode)
    cutoff = cutoff_for(req.user_preference)
    complexity = "complex" if score_prompt(text) >= cutoff else "simple"
    downgraded = complexity == "simple"
    return PickModelResponse(
        complexity=complexity,
        recommended_model=SMALL_MODEL if downgraded else DEFAULT_MODEL,
        default_model=DEFAULT_MODEL,
        estimated_savings=_estimate_savings(downgraded),
    )