"""
Entrypoint — runs all scrapers, dedupes, filters, posts to Slack.
"""

import logging
from bot.scrapers.yc import scrape_yc
from bot.scrapers.greenhouse import scrape_greenhouse
from bot.scrapers.lever import scrape_lever
from bot.scrapers.wellfound import scrape_wellfound
from bot.scrapers.linkedin import scrape_linkedin
from bot.scrapers.orbiter import scrape_orbiter
from bot.filters import is_sponsored
from bot.deduper import filter_new, mark_seen
from bot.slack import post_digest

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def run():
    log.info("🚀 Starting O1 job scrape…")

    raw = []
    for scraper in [scrape_yc, scrape_greenhouse, scrape_lever,
                    scrape_wellfound, scrape_linkedin, scrape_orbiter]:
        try:
            raw += scraper()
        except Exception as e:
            log.error(f"{scraper.__name__} failed: {e}")

    log.info(f"Raw listings collected: {len(raw)}")

    filtered = [j for j in raw if is_sponsored(j.get("company", ""), j.get("description", ""))]
    log.info(f"After visa filter: {len(filtered)}")

    new_jobs = filter_new(filtered)
    log.info(f"New this week: {len(new_jobs)}")

    if not new_jobs:
        log.info("No new jobs — skipping Slack post.")
        return

    post_digest(new_jobs)
    mark_seen(new_jobs)
    log.info("✅ Done.")


if __name__ == "__main__":
    run()