"""Scraper — Wellfound (AngelList) via Playwright headless browser"""

import logging
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
URL = "https://wellfound.com/jobs?role=engineer&remote=true"


def scrape_wellfound() -> list[dict]:
    log.info("Scraping Wellfound…")
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(URL, timeout=30000)
            page.wait_for_selector("[data-test='JobSearchResult']", timeout=15000)
            for card in page.query_selector_all("[data-test='JobSearchResult']")[:30]:
                title_el = card.query_selector("h2") or card.query_selector("h3")
                company_el = card.query_selector("[class*='company']")
                link_el = card.query_selector("a[href*='/jobs/']")
                loc_el = card.query_selector("[class*='location']")
                desc_el = card.query_selector("[class*='description']")

                title = title_el.inner_text().strip() if title_el else ""
                company = company_el.inner_text().strip() if company_el else ""
                loc = loc_el.inner_text().strip() if loc_el else "Remote"
                desc = desc_el.inner_text().strip() if desc_el else ""
                href = link_el.get_attribute("href") if link_el else ""
                url = f"https://wellfound.com{href}" if href.startswith("/") else href

                if title:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": loc,
                        "description": desc,
                        "url": url,
                        "source": "Wellfound",
                    })
        except Exception as e:
            log.error(f"Wellfound scraper failed: {e}")
        finally:
            browser.close()
    log.info(f"Wellfound → {len(jobs)} jobs")
    return jobs
