import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def parse_json_response(raw_text: Optional[str]) -> Optional[dict]:
    """Parse Claude's JSON response with fallbacks for markdown wrapping."""
    if not raw_text:
        return None

    text = raw_text.strip()

    # Attempt 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: Extract from ```json ... ``` block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Attempt 3: Find first { ... } in text (greedy to catch full object)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.error(f"Failed to parse JSON from AI response: {text[:300]}")
    return None
