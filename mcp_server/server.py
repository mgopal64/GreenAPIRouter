"""Green Router as an MCP server: lets AI assistants and agents pick the lightest adequate model
for a prompt and split a batch of calls across greener Azure regions.

A thin client over the Green Router HTTP API (so rate limits, validation and data sources stay in
one place). It never makes live model calls, so an agent can't spend Azure credits through it.

Run (stdio):  .venv/bin/python mcp_server/server.py
Backend URL:  GREENROUTER_URL (default http://localhost:8000)
"""
import logging
import os
from typing import Annotated
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

API_URL = os.getenv("GREENROUTER_URL", "http://localhost:8000").rstrip("/")
if urlparse(API_URL).scheme not in ("http", "https"):
    raise SystemExit("GREENROUTER_URL must start with http:// or https://")

# httpx logs every request at INFO; keep the MCP client's logs readable.
logging.getLogger("httpx").setLevel(logging.WARNING)

REGION_LABELS = {"westus": "West US", "northcentralus": "North Central US"}
ERRORS = {
    422: "The request was rejected as invalid (check the prompt length and weights).",
    429: "Green Router is rate limited right now. Wait a minute and try again.",
}
# Both tools only read: no side effects, safe to retry.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

mcp = MCPServer(
    name="green-router",
    instructions=(
        "Green Router reduces the carbon and water footprint of AI calls. Use pick_model before sending "
        "a prompt to an LLM to find the lightest model that can handle it, and route_calls to split a "
        "batch of calls across Azure regions by grid carbon and watershed stress. Numbers come from "
        "static estimates unless grid_source says live EIA data."
    ),
)


async def _post(path: str, body: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{API_URL}{path}", json=body)
    except httpx.HTTPError:
        raise ToolError(f"Can't reach the Green Router backend at {API_URL}. Is it running?") from None
    if res.status_code != 200:
        raise ToolError(ERRORS.get(res.status_code, f"Green Router request failed ({res.status_code})."))
    return res.json()


@mcp.tool(annotations=READ_ONLY)
async def pick_model(
    prompt: Annotated[str, Field(description="The prompt you are about to send to an LLM.", min_length=1, max_length=4000)],
    preference: Annotated[float, Field(
        description="Eco vs quality, 0-1. 0 = max eco (small model more often), 0.5 = validated default, "
                    "1 = max quality (large model unless the prompt is simple).", ge=0, le=1)] = 0.5,
    clean_whitespace: Annotated[bool, Field(
        description="Collapse extra blank lines and spaces before scoring (the prompt itself is not changed).")] = True,
) -> dict:
    """Recommend the lightest model that can handle a prompt, and the energy, CO2 and water saved per call
    compared with always using the large default model. Savings are estimated from token counts."""
    r = await _post("/pick-model", {
        "prompt": prompt,
        "user_preference": preference,
        "simplification_mode": "structural" if clean_whitespace else "none",
    })
    s = r["estimated_savings"]
    downgraded = r["recommended_model"] != r["default_model"]
    r["summary"] = (
        f"Use {r['recommended_model']} ({r['complexity']} prompt). Saves ~{s['energy_wh']} Wh, "
        f"{s['co2_g']} g CO2 and {s['water_ml']} mL water per call vs {r['default_model']} "
        f"(~{s['energy_wh'] * 1000:.3g} kWh per 1M calls)."
        if downgraded
        else f"This prompt needs {r['recommended_model']} ({r['complexity']} prompt); no smaller model fits."
    )
    return r


@mcp.tool(annotations=READ_ONLY)
async def route_calls(
    num_calls: Annotated[int, Field(description="How many AI calls to route.", ge=1, le=10_000_000)] = 1000,
    carbon_weight: Annotated[float, Field(description="Priority on low grid carbon, 0-1.", ge=0, le=1)] = 0.5,
    water_weight: Annotated[float, Field(description="Priority on low watershed stress, 0-1.", ge=0, le=1)] = 0.5,
) -> dict:
    """Split a batch of AI calls across Azure regions by grid carbon and watershed stress, with the CO2
    and water impact compared with sending everything to the default region. Water impact is liters
    used times local watershed stress (0-1)."""
    r = await _post("/route", {
        "provider": "azure",
        "num_calls": num_calls,
        "weights": {"carbon": carbon_weight, "water": water_weight},
    })
    split = ", ".join(
        f"{REGION_LABELS.get(d['region'], d['region'])} {round(d['share'] * 100)}%" for d in r["distribution"]
    )
    s = r["savings"]
    naive = REGION_LABELS.get(r["naive_baseline"]["region"], r["naive_baseline"]["region"])
    sources = sorted({d["grid_source"] for d in r["distribution"]})

    def change(pct: float, what: str) -> str:
        return f"{abs(pct)}% {'less' if pct >= 0 else 'more'} {what}"

    r["summary"] = (
        f"Send {split}. {change(s['pct_co2'], 'CO2')} and {change(s['pct_water_stress'], 'water impact')} "
        f"than sending all {num_calls} calls to {naive}. Data: {', '.join(sources)}."
    )
    return r


if __name__ == "__main__":
    mcp.run("stdio")
