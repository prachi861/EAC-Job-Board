"""Scraper — Y Combinator Work at a Startup board (public JSON API)"""

import logging
import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def scrape_yc() -> list[dict]:
    log.info("Scraping YC…")
    jobs = []
    try:
        r = requests.get(
            "https://api.workatastartup.com/jobs?query=&remote=&sponsor=true",
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        for job in r.json().get("jobs", []):
            jobs.append({
                "title": job.get("title", ""),
                "company": job.get("company", {}).get("name", ""),
                "location": job.get("location", "Remote"),
                "description": job.get("description", ""),
                "url": f"https://www.workatastartup.com/jobs/{job.get('id')}",
                "source": "YC",
            })
    except Exception as e:
        log.error(f"YC scraper failed: {e}")
    log.info(f"YC → {len(jobs)} jobs")
    return jobs
