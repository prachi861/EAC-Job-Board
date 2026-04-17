"""Scraper — Lever public postings API"""

import time
import logging
import requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# slug → display name (only verified working slugs)
# Only slugs that have been confirmed working recently
LEVER_COMPANIES = {
    "anyscale":     "Anyscale",
    "mistral":      "Mistral",
    "carta":        "Carta",
    "deel":         "Deel",
    "ramp":         "Ramp",
    "samsara":      "Samsara",
}


def scrape_lever() -> list[dict]:
    log.info("Scraping Lever…")
    jobs = []
    for slug, company_name in LEVER_COMPANIES.items():
        try:
            r = requests.get(
                f"https://api.lever.co/v0/postings/{slug}?mode=json",
                headers=HEADERS, timeout=8,
            )
            r.raise_for_status()
            for job in r.json():
                posted = None
                created_at = job.get("createdAt")
                if created_at:
                    try:
                        posted = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                    except Exception:
                        pass
                desc = job.get("descriptionPlain", "") + " " + job.get("additionalPlain", "")
                jobs.append({
                    "title":       job.get("text", ""),
                    "company":     company_name,
                    "location":    job.get("categories", {}).get("location", "Remote"),
                    "description": desc.strip(),
                    "url":         job.get("hostedUrl", ""),
                    "source":      "Lever",
                    "posted_at":   posted,
                })
        except Exception as e:
            log.warning(f"Lever {slug} failed: {e}")
        time.sleep(0.3)
    log.info(f"Lever → {len(jobs)} jobs")
    return jobs
