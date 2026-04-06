import os
import logging
import requests
from datetime import datetime

log = logging.getLogger(__name__)

WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]


def _header_block(total: int) -> dict:
    date = datetime.now().strftime("%B %d, %Y")
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*O1-Friendly Job Board — {date}*\n"
                f"_{total} curated roles from companies that sponsor visas._"
            ),
        },
    }


def _job_block(job: dict) -> dict:
    url = job.get("url", "")
    location = job.get("location", "Remote")
    industry = job.get("industry", "")
    posted = job.get("posted_at")
    posted_str = posted.strftime("%b %d") if posted else ""

    meta_parts = [location]
    if industry:
        meta_parts.append(industry)
    if posted_str:
        meta_parts.append(f"Posted {posted_str}")
    meta = "  ·  ".join(meta_parts)

    link = f"<{url}|{job['title']}>" if url else job["title"]

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{link}*\n{job['company']}  —  {meta}",
        },
    }


def _footer_block(total: int) -> dict:
    shown = min(total, 20)
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Showing {shown} of {total} roles · Know a listing we missed? Drop it in the thread.",
            }
        ],
    }


def post_digest(jobs: list):
    capped = jobs[:20]
    blocks = [
        _header_block(len(jobs)),
        {"type": "divider"},
    ]
    for job in capped:
        blocks.append(_job_block(job))
        blocks.append({"type": "divider"})
    blocks.append(_footer_block(len(jobs)))

    r = requests.post(WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    if r.status_code == 200:
        log.info(f"Posted {len(capped)} jobs to Slack.")
    else:
        log.error(f"Slack error {r.status_code}: {r.text}")
        raise RuntimeError("Slack post failed")
