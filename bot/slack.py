import os
import logging
import requests
from datetime import datetime

log = logging.getLogger(__name__)

WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

SOURCE_EMOJI = {
    "YC": "🚀", "Wellfound": "🌐", "Greenhouse": "🌿",
    "Lever": "⚙️", "LinkedIn": "💼", "Orbiter": "🛸",
}


def _header_block(total: int) -> dict:
    date = datetime.now().strftime("%B %d, %Y")
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"👋 *Happy Monday — O1-Friendly Job Drop | {date}*\n"
                f"_{total} new visa-sponsoring roles this week._\n"
                f"{'━' * 40}"
            ),
        },
    }


def _job_block(job: dict) -> dict:
    emoji = SOURCE_EMOJI.get(job.get("source", ""), "📌")
    url = job.get("url", "")
    link = f"<{url}|View Listing>" if url else "No link"
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"{emoji} *{job['title']}* — {job['company']}\n"
                f"📍 {job.get('location', 'Remote')}  ·  🔗 {link}  ·  `{job.get('source', '')}`"
            ),
        },
    }


def _footer_block(total: int) -> dict:
    shown = min(total, 20)
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"_Showing {shown} of {total} listings. Know a role we missed? Drop it in the thread 🧵_",
        },
    }


def post_digest(jobs: list):
    capped = jobs[:20]
    blocks = [_header_block(len(jobs))]
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
