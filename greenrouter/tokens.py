"""Token estimates for impact *before* a call is made (the picker's savings).

Live calls don't use this: /complete gets the real token counts from Azure's `usage` and
accounting.py turns those into energy, CO2 and water. Estimates here go through the same
accounting.impact() formula, so estimated and real numbers are directly comparable.
"""
import math

# OpenAI's rule of thumb for English text. Close enough for an estimate, and needs no tokenizer
# download (tiktoken fetches its encoding files at runtime).
CHARS_PER_TOKEN = 4

# PLACEHOLDER, owned by the stats teammate: typical completion length per complexity, including
# gpt-5-mini reasoning tokens. Replace with measured averages from the TigerData `calls` table
# once live calls are logged.
TYPICAL_OUTPUT_TOKENS = {"simple": 300, "medium": 600, "complex": 1200}


def prompt_tokens(text: str) -> int:
    """Approximate token count of a prompt."""
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def output_tokens(complexity: str) -> int:
    """Assumed completion length for a prompt of this complexity."""
    return TYPICAL_OUTPUT_TOKENS.get(complexity, TYPICAL_OUTPUT_TOKENS["medium"])
