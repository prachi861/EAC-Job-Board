"""Scraper — Greenhouse public jobs API"""

import time
import logging
import requests
from datetime import datetime

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

GREENHOUSE_SLUGS = [
    # AI/ML
    "anthropic", "openai", "cohereai", "databricks", "scaleai",
    "anyscale", "perplexityai", "adept",
    # SWE / Infra
    "stripe", "vercel", "hashicorp", "datadoghq", "confluent",
    "airbyte", "figma",
    # Data
    "fivetran", "hightouch",
    # Fintech
    "brex", "plaid", "coinbase", "robinhood", "ramp", "mercury",
    # Design / Product
    "miro", "loom", "airtable",
    # Science / Hardware
    "nvidiacareers", "benchling", "recursion", "tempus",
    # Consumer
    "airbnb", "doordash", "instacart", "reddit",
    # Renewable / EV
    "formenergy", "samsara", "lucidmotors",
]


def scrape_greenhouse() -> list[dict]:
    log.info("Scraping Greenhouse…")
    jobs = []
    for slug in GREENHOUSE_SLUGS:
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                headers=HEADERS, timeout=15,
            )
            r.raise_for_status()
            for job in r.json().get("jobs", [])[:50]:
                posted = None
                updated_at = job.get("updated_at")
                if updated_at:
                    try:
                        posted = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except Exception:
                        pass
                company_name = slug.replace("-", " ").title()
                jobs.append({
                    "title":       job.get("title", ""),
                    "company":     company_name,
                    "location":    job.get("location", {}).get("name", "Remote"),
                    "description": job.get("content", ""),
                    "url":         job.get("absolute_url", ""),
                    "source":      "Greenhouse",
                    "posted_at":   posted,
                })
        except Exception as e:
            log.warning(f"Greenhouse {slug} failed: {e}")
        time.sleep(0.3)
    log.info(f"Greenhouse → {len(jobs)} jobs")
    return jobs
