"""Calls the team's Azure OpenAI deployments.

Endpoints and keys are read only from the server environment and never returned to clients.
"""
import os
from urllib.parse import urlparse

import httpx

# Region name -> env var prefix (e.g. WESTUS_ENDPOINT, WESTUS_KEY).
_ENV_PREFIX = {"westus": "WESTUS", "northcentralus": "NCUS"}
MAX_COMPLETION_TOKENS = 1000  # caps cost per call; includes reasoning tokens for gpt-5 models
TIMEOUT_S = 30


class AzureError(Exception):
    """Upstream call failed. The message is for server logs only, never for clients."""


def deployment(size: str) -> str:
    name = os.getenv(f"{size.upper()}_DEPLOYMENT", "").strip()
    if not name:
        raise AzureError(f"{size.upper()}_DEPLOYMENT is not set")
    return name


def _config(region: str) -> tuple[str, str]:
    prefix = _ENV_PREFIX.get(region)
    endpoint = os.getenv(f"{prefix}_ENDPOINT", "").strip() if prefix else ""
    key = os.getenv(f"{prefix}_KEY", "").strip() if prefix else ""
    if not endpoint or not key:
        raise AzureError(f"No endpoint/key configured for region {region}")
    url = urlparse(endpoint)
    # Only ever send the key to an Azure OpenAI host over HTTPS.
    if url.scheme != "https" or not (url.hostname or "").endswith(".openai.azure.com"):
        raise AzureError(f"Refusing non-Azure endpoint for region {region}")
    return endpoint.rstrip("/"), key


async def chat(region: str, deployment_name: str, prompt: str) -> tuple[str, int, int]:
    """Send one prompt. Returns (output text, prompt tokens, completion tokens)."""
    endpoint, key = _config(region)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(
                f"{endpoint}/chat/completions",
                headers={"api-key": key},
                json={
                    "model": deployment_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": MAX_COMPLETION_TOKENS,
                },
            )
    except httpx.HTTPError as e:
        raise AzureError(f"{region}: {type(e).__name__}") from None
    if resp.status_code != 200:
        raise AzureError(f"{region}: HTTP {resp.status_code}")
    try:
        data = resp.json()
        text = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage", {})
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    except (ValueError, KeyError, IndexError, TypeError):
        raise AzureError(f"{region}: unexpected response shape") from None
