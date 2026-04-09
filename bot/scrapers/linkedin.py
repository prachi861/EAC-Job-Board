"""Scraper — LinkedIn public job search via Playwright headless browser"""

import time
import logging
import requests
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

QUERIES = [
    "data engineer visa sponsorship United States",
    "machine learning engineer o1 visa United States",
    "backend software engineer visa sponsorship United States",
    "product designer visa sponsorship remote US",
    "fp&a manager visa sponsorship United States",
    "renewable energy engineer visa sponsorship United States",
    "business analyst visa sponsorship remote US",
    "devops engineer visa sponsorship United States",
    "data analyst visa sponsorship United States",
    "ai engineer visa sponsorship United States",
]


def scrape_linkedin() -> list[dict]:
    log.info("Scraping LinkedIn…")
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        for q in QUERIES:
            encoded = requests.utils.quote(q)
            url = f"https://www.linkedin.com/jobs/search/?keywords={encoded}&f_JT=F&location=United%20States"
            try:
                page.goto(url, timeout=30000)
                page.wait_for_selector(".job-search-card", timeout=15000)
                for card in page.query_selector_all(".job-search-card")[:8]:
                    title_el   = card.query_selector(".base-search-card__title")
                    company_el = card.query_selector(".base-search-card__subtitle")
                    loc_el     = card.query_selector(".job-search-card__location")
                    link_el    = card.query_selector("a.base-card__full-link")

                    title   = title_el.inner_text().strip() if title_el else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc     = loc_el.inner_text().strip() if loc_el else "Remote"
                    href    = link_el.get_attribute("href") if link_el else ""

                    if title and href.startswith("http"):
                        jobs.append({
                            "title":       title,
                            "company":     company,
                            "location":    loc,
                            "description": q,
                            "url":         href,
                            "source":      "LinkedIn",
                        })
            except Exception as e:
                log.warning(f"LinkedIn query '{q}' failed: {e}")
            time.sleep(3)
        browser.close()
    log.info(f"LinkedIn → {len(jobs)} jobs")
    return jobs
