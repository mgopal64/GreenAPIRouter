"""Model picker.

PLACEHOLDER — owned by the model-selection teammate. Replace `pick_model` with the real
picker; keep the signature so main.py doesn't change.
"""
from .regions import WATER_L_PER_KWH
from .schemas import EstimatedSavings, PickModelRequest, PickModelResponse


def pick_model(req: PickModelRequest) -> PickModelResponse:
    # Placeholder: picks by word count only, and the savings numbers are made up.
    n = len(req.prompt.split())
    if n < 30:
        complexity, model = "simple", "gpt-4.1-mini"
    elif n < 150:
        complexity, model = "medium", "gpt-4.1-mini"
    else:
        complexity, model = "complex", "gpt-5-mini"
    saved = {"simple": 2.4, "medium": 2.4, "complex": 0.0}[complexity]
    return PickModelResponse(
        complexity=complexity,
        recommended_model=model,
        default_model="gpt-5-mini",
        estimated_savings=EstimatedSavings(
            energy_wh=saved, co2_g=round(saved * 0.39, 3), water_ml=round(saved * WATER_L_PER_KWH, 3)
        ),
    )
