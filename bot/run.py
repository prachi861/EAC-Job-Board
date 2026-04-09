"""
Entrypoint — runs all scrapers, dedupes, filters, posts to Slack.
Selects up to 15 diverse roles across unique companies and target industries.
"""

import logging
from bot.scrapers.greenhouse import scrape_greenhouse
from bot.scrapers.lever import scrape_lever
from bot.scrapers.linkedin import scrape_linkedin
from bot.filters import is_sponsored
from bot.deduper import filter_new, mark_seen
from bot.slack import post_digest

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

INDUSTRY_KEYWORDS = {
    "AI/ML Engineering":      [
        "machine learning engineer", "ml engineer", "ai engineer",
        "artificial intelligence engineer", "llm engineer", "nlp engineer",
        "deep learning engineer", "genai engineer", "research engineer",
        "applied scientist", "ai scientist", "ai researcher", "ml researcher",
        "ai/ml engineer", "generative ai",
    ],
    "Software Engineering":   [
        "software engineer", "backend engineer", "frontend engineer",
        "full stack engineer", "fullstack engineer", "full-stack engineer",
        "react engineer", "java engineer", "java developer", "web developer",
        "swe", "sde", "distributed systems engineer", "devops engineer",
        "platform engineer", "infrastructure engineer", "systems engineer",
        "android engineer", "ios engineer", "mobile engineer",
    ],
    "Data & Analytics":       [
        "data engineer", "data scientist", "data analyst", "analytics engineer",
        "business analyst", "data platform engineer", "data quality engineer",
        "power bi developer", "database reliability engineer", "postgresql engineer",
        "staff data engineer", "data science intern", "analytics intern",
        "database administrator", "data analytics",
    ],
    "Product & Design":       [
        "product manager", "product designer", "ux designer", "ui/ux designer",
        "ui designer", "product design", "product marketing manager",
        "project manager", "program manager", "ux researcher",
        "people operations", "hr analyst",
    ],
    "IT & Infrastructure":    [
        "it manager", "it software", "sap fico", "data platform engineer",
        "cloud engineer", "database admin", "database reliability",
        "site reliability engineer", "sre",
    ],
    "Engineering & Science":  [
        "mechanical engineer", "process engineer", "electrical engineer",
        "semiconductor engineer", "thin film", "renewable energy engineer",
        "bess engineer", "power electronics engineer", "ev powertrain",
        "battery engineer", "energy storage engineer", "staff scientist",
    ],
    "Finance & Strategy":     [
        "fp&a", "financial analyst", "finance manager", "strategic finance",
        "business analytics", "people analytics", "fp&a manager",
    ],
    "Sports & Emerging Tech": [
        "sports technology", "sports analytics", "aviation engineer",
    ],
}

NON_US_TERMS = [
    "ireland", "dublin", "remote - ireland", "remote, ireland",
    "united kingdom", "london", "remote - uk", "remote, uk", " uk,", "(uk)",
    "canada", "toronto", "vancouver", "remote - ca", "remote, canada",
    "australia", "sydney", "melbourne",
    "india", "bangalore", "bengaluru", "hyderabad",
    "germany", "berlin", "munich",
    "france", "paris",
    "netherlands", "amsterdam",
    "singapore",
    "new zealand", "auckland",
    "remote - eu", "remote, eu", "europe",
]

US_TERMS = [
    "united states", "usa", " us,", "(us)", "remote, us", "remote (us)",
    "us remote", "remote - us", "new york", "san francisco", "seattle",
    "austin", "boston", "chicago", "los angeles", "denver", "atlanta",
    "miami", "washington", "nyc", "sf", "bay area", "mountain view",
    "palo alto", "san jose", "portland", "philadelphia", "dallas", "houston",
    "phoenix", "san diego", "raleigh", "minneapolis", "bellevue", "menlo park",
    "remote",
]


def classify(title: str) -> str:
    t = title.lower()
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return industry
    return "Other"


def is_us(job: dict) -> bool:
    loc = job.get("location", "").lower().strip()
    if not loc:
        return True
    if any(t in loc for t in NON_US_TERMS):
        return False
    if any(t in loc for t in US_TERMS):
        return True
    return False


def diversify(jobs: list, target: int = 15) -> list:
    from datetime import timezone, datetime
    now = datetime.now(tz=timezone.utc)

    def sort_key(j):
        p = j.get("posted_at")
        if p is None:
            return (1, now)
        return (0, -p.timestamp())

    # Priority: target industries first, "Other" last; within each group, newest first
    priority = sorted([j for j in jobs if j.get("industry") != "Other"], key=sort_key)
    other    = sorted([j for j in jobs if j.get("industry") == "Other"],    key=sort_key)
    jobs = priority + other

    seen_companies = {}
    industry_counts = {k: 0 for k in INDUSTRY_KEYWORDS}
    industry_counts["Other"] = 0
    selected = []

    for job in jobs:
        company  = job.get("company", "").lower().strip()
        industry = job.get("industry", "Other")

        if company and seen_companies.get(company, 0) >= 2:
            continue
        if industry_counts.get(industry, 0) >= 3:
            continue

        seen_companies[company] = seen_companies.get(company, 0) + 1
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        selected.append(job)

        if len(selected) >= target:
            break

    return selected


def run():
    log.info("Starting O1 job scrape…")

    raw = []
    for scraper in [scrape_greenhouse, scrape_lever, scrape_linkedin]:
        try:
            results = scraper()
            log.info(f"{scraper.__name__} → {len(results)} raw jobs")
            raw += results
        except Exception as e:
            log.error(f"{scraper.__name__} failed: {e}")

    log.info(f"Total raw listings: {len(raw)}")

    # 1. Classify — target industries first, rest = "Other"
    for j in raw:
        j["industry"] = classify(j.get("title", ""))

    # 2. Visa sponsorship filter
    filtered = [j for j in raw if is_sponsored(j.get("company", ""), j.get("description", ""))]
    log.info(f"After visa filter: {len(filtered)}")

    # 3. US-only filter
    filtered = [j for j in filtered if is_us(j)]
    log.info(f"After US filter: {len(filtered)}")

    # 4. Drop jobs with no valid direct URL
    filtered = [j for j in filtered if j.get("url", "").startswith("http")]
    log.info(f"After URL filter: {len(filtered)}")

    # 5. Dedup against previously seen jobs
    new_jobs = filter_new(filtered)
    log.info(f"New this week: {len(new_jobs)}")

    if not new_jobs:
        log.info("No new jobs — skipping Slack post.")
        return

    # 6. Pick 15 diverse roles
    diverse = diversify(new_jobs, target=15)
    industries = set(j["industry"] for j in diverse)
    log.info(f"Final selection: {len(diverse)} jobs across {len(industries)} industries: {industries}")

    post_digest(diverse)
    mark_seen(new_jobs)
    log.info("Done.")


if __name__ == "__main__":
    run()
