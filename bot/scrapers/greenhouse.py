"""Scraper — Greenhouse public jobs API"""

import time
import logging
import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

COMPANY_SLUGS = [
    "openai", "anthropic", "stripe", "notion", "linear", "figma",
    "brex", "rippling", "retool", "scale", "cohere", "databricks",
    "nvidia", "palantir", "coinbase", "robinhood", "plaid", "airbnb",
]


def scrape_greenhouse() -> list[dict]:
    log.info("Scraping Greenhouse…")
    jobs = []
    for slug in COMPANY_SLUGS:
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                headers=HEADERS,
                timeout=15,
            )
            r.raise_for_status()
            for job in r.json().get("jobs", []):
                jobs.append({
                    "title": job.get("title", ""),
                    "company": slug.replace("-", " ").title(),
                    "location": job.get("location", {}).get("name", "Remote"),
                    "description": job.get("content", ""),
                    "url": job.get("absolute_url", ""),
                    "source": "Greenhouse",
                })
        except Exception as e:
            log.warning(f"Greenhouse {slug} failed: {e}")
        time.sleep(0.5)
    log.info(f"Greenhouse → {len(jobs)} jobs")
    return jobs
