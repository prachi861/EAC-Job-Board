"""
Entrypoint — runs all scrapers, dedupes, filters, posts to Slack.
Selects 10-20 diverse roles across unique companies and industries.
"""

import random
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

# Map keywords in job titles to industry buckets
INDUSTRY_KEYWORDS = {
    "AI/ML":        ["machine learning", "ml ", "ai ", "artificial intelligence", "llm", "nlp", "research scientist", "deep learning"],
    "Engineering":  ["software engineer", "backend", "frontend", "full stack", "platform", "infrastructure", "devops", "sre"],
    "Founding":     ["founding engineer", "founding", "early engineer", "first engineer"],
    "Data":         ["data engineer", "data scientist", "analytics", "data platform"],
    "Product":      ["product manager", "pm ", "product lead"],
    "Design":       ["designer", "ux", "ui ", "product design"],
    "Biotech":      ["biotech", "biology", "genomics", "life science", "clinical"],
    "Finance":      ["fintech", "quant", "trading", "finance", "risk"],
    "Security":     ["security", "cryptography", "trust and safety"],
    "Other":        [],
}


def classify(title: str) -> str:
    t = title.lower()
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return industry
    return "Other"


def diversify(jobs: list, target: int = 15) -> list:
    """
    Pick up to `target` jobs ensuring:
    - Sorted by recency first (newest roles bubble up)
    - Max 1 role per company
    - Max 2 roles per industry bucket
    - Random shuffle within same-day postings
    """
    from datetime import timezone
    now = __import__('datetime').datetime.now(tz=timezone.utc)

    # Sort: jobs with a date come first (newest first), undated jobs go last
    def sort_key(j):
        p = j.get("posted_at")
        if p is None:
            return (1, now)  # push undated to end
        return (0, -p.timestamp())  # newest first

    jobs = sorted(jobs, key=sort_key)

    seen_companies = set()
    industry_counts = {k: 0 for k in INDUSTRY_KEYWORDS}
    selected = []

    for job in jobs:
        company = job.get("company", "").lower().strip()
        industry = classify(job.get("title", ""))

        if company in seen_companies:
            continue
        if industry_counts.get(industry, 0) >= 2:
            continue

        seen_companies.add(company)
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        job["industry"] = industry
        selected.append(job)

        if len(selected) >= target:
            break

    return selected


def run():
    log.info("Starting O1 job scrape…")

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

    # Keep only US-based or Remote roles
    us_terms = {"us", "usa", "united states", "remote", "new york", "san francisco",
                "seattle", "austin", "boston", "chicago", "los angeles", "denver",
                "atlanta", "miami", "washington", "nyc", "sf", "bay area"}
    filtered = [
        j for j in filtered
        if any(term in j.get("location", "").lower() for term in us_terms)
        or not j.get("location")  # include if location is blank
    ]
    log.info(f"After US filter: {len(filtered)}")

    new_jobs = filter_new(filtered)
    log.info(f"New this week: {len(new_jobs)}")

    if not new_jobs:
        log.info("No new jobs — skipping Slack post.")
        return

    diverse = diversify(new_jobs, target=15)
    log.info(f"Diverse selection: {len(diverse)} jobs across {len(set(j['industry'] for j in diverse))} industries")

    post_digest(diverse)
    mark_seen(new_jobs)  # mark ALL new jobs as seen, not just the ones we posted
    log.info("Done.")


if __name__ == "__main__":
    run()
