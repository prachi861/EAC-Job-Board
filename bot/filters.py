"""
Visa sponsorship detection — checks known sponsor list and job description text.
"""

import re

KNOWN_SPONSORS: set[str] = {
    "google", "meta", "apple", "microsoft", "amazon", "stripe", "openai",
    "anthropic", "databricks", "figma", "notion", "linear", "scale ai",
    "cohere", "mistral", "hugging face", "deepmind", "nvidia", "palantir",
    "spacex", "tesla", "airbnb", "doordash", "instacart", "coinbase",
    "robinhood", "plaid", "brex", "rippling", "lattice", "retool",
}

VISA_RE = re.compile(
    r"(visa sponsorship|o-?1|eb-?1|h-?1b|work authorization|sponsor.{0,20}visa)",
    re.IGNORECASE,
)


def is_sponsored(company: str, description: str) -> bool:
    return company.lower().strip() in KNOWN_SPONSORS or bool(VISA_RE.search(description or ""))
