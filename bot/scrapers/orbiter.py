"""Scraper — Orbiter.club visa-friendly job board"""

import re
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def scrape_orbiter() -> list[dict]:
    log.info("Scraping Orbiter…")
    jobs = []
    try:
        r = requests.get("https://orbiter.club/jobs", headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select(".job-card, [class*='job'], article"):
            title_el = card.find(["h2", "h3", "h4"])
            link_el = card.find("a", href=True)
            company_el = card.find(class_=re.compile("company|employer", re.I))
            loc_el = card.find(class_=re.compile("location|loc", re.I))
            desc_el = card.find(class_=re.compile("desc|summary", re.I))

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            loc = loc_el.get_text(strip=True) if loc_el else "Remote"
            desc = desc_el.get_text(strip=True) if desc_el else ""
            href = link_el["href"] if link_el else ""
            url = href if href.startswith("http") else f"https://orbiter.club{href}"

            if title:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "description": desc,
                    "url": url,
                    "source": "Orbiter",
                })
    except Exception as e:
        log.error(f"Orbiter scraper failed: {e}")
    log.info(f"Orbiter → {len(jobs)} jobs")
    return jobs
