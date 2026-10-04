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

def _num(x: float) -> str:
    """Readable number: 1,625 rather than 1.63e+03; small values keep 3 significant digits."""
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"


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
        "Green Router reduces the carbon and water footprint of AI calls. Use pick_model (or pick_models "
        "for a batch) before sending prompts to an LLM to find the lightest model that can handle them, and "
        "route_calls to split a batch of calls across Azure regions by grid carbon and watershed stress. "
        "region_snapshot and grid_replay show the grid data behind the routing; savings_so_far reports real "
        "savings from logged live calls. Numbers come from static estimates unless grid_source says EIA data."
    ),
)


async def _post(path: str, body: dict) -> dict:
    return await _request("POST", path, json=body)


async def _get(path: str, params: dict | None = None) -> dict | list:
    return await _request("GET", path, params=params)


async def _request(method: str, path: str, **kwargs) -> dict | list:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.request(method, f"{API_URL}{path}", **kwargs)
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
        f"(~{_num(s['energy_wh'] * 1000)} kWh per 1M calls)."
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



@mcp.tool(annotations=READ_ONLY)
async def pick_models(
    prompts: Annotated[list[Annotated[str, Field(min_length=1, max_length=4000)]], Field(
        description="Up to 50 prompts to score in one go.", min_length=1, max_length=50)],
    preference: Annotated[float, Field(
        description="Eco vs quality, 0-1 (same as pick_model). 0.5 = validated default.", ge=0, le=1)] = 0.5,
    clean_whitespace: Annotated[bool, Field(description="Collapse extra blank lines and spaces before scoring.")] = True,
) -> dict:
    """Recommend a model for many prompts at once (one model pass), with total estimated savings vs always
    using the large default model. Use this instead of calling pick_model in a loop."""
    r = await _post("/pick-model/batch", {
        "prompts": prompts,
        "user_preference": preference,
        "simplification_mode": "structural" if clean_whitespace else "none",
    })
    results = r["results"]
    small = sum(x["recommended_model"] != x["default_model"] for x in results)
    wh = sum(x["estimated_savings"]["energy_wh"] for x in results)
    co2 = sum(x["estimated_savings"]["co2_g"] for x in results)
    r["summary"] = (
        f"{small} of {len(results)} prompts can use the smaller model. Estimated savings for this batch: "
        f"{_num(wh)} Wh and {_num(co2)} g CO2 (~{_num(wh / len(results) * 1000)} kWh per 1M prompts like these)."
    )
    return r


@mcp.tool(annotations=READ_ONLY)
async def savings_so_far(
    hours: Annotated[int, Field(description="Look-back window in hours (1-720).", ge=1, le=720)] = 24,
) -> dict:
    """Real savings from live calls logged in the last `hours`: actual energy, CO2, water and cost vs the
    naive setup (large model, default region), from Azure's real token counts."""
    r = await _get("/summary", {"hours": hours})
    p = r.get("pct_saved", {})
    r["summary"] = (
        f"{r.get('calls', 0)} live calls in the last {hours} h. Saved vs naive: {p.get('energy_wh', 0)}% energy, "
        f"{p.get('co2_g', 0)}% CO2, {p.get('water_ml', 0)}% water, {p.get('cost_usd', 0)}% cost."
        if r.get("calls") else f"No live calls logged in the last {hours} h."
    )
    return r


@mcp.tool(annotations=READ_ONLY)
async def region_snapshot() -> dict:
    """Current grid carbon, water use and watershed stress for each Azure region, plus the nearby power
    plants that feed it. Explains why route_calls prefers one region over another."""
    regions = await _get("/regions")
    lines = [
        f"{REGION_LABELS.get(r['region'], r['region'])}: {r['gco2_per_kwh']} gCO2/kWh, "
        f"{r['stress_weighted_l_per_kwh']} L/kWh stress-weighted water, site stress {r['site_stress']} "
        f"({len(r.get('plants', []))} plants, {r['grid_source']} data)"
        for r in regions
    ]
    return {"regions": regions, "summary": " | ".join(lines)}


@mcp.tool(annotations=READ_ONLY)
async def grid_replay(
    hours: Annotated[int, Field(description="How many recent hours of grid data (1-168).", ge=1, le=168)] = 24,
) -> dict:
    """Hourly grid carbon and stress-weighted water per region for recent hours, and which region was best
    each hour on carbon and on water. Shows how the greenest region changes through the day."""
    r = await _get("/replay", {"hours": hours})
    winners = r.get("winners", [])
    def tally(key):
        counts = {}
        for w in winners:
            name = REGION_LABELS.get(w[key], w[key])
            counts[name] = counts.get(name, 0) + 1
        return ", ".join(f"{k} {v}h" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) or "no data"
    r["summary"] = (
        f"Over {len(winners)} hours of EIA data: best on carbon: {tally('carbon')}; "
        f"best on water: {tally('water')}."
    )
    return r


if __name__ == "__main__":
    mcp.run("stdio")
