"""
DM flow — reads member profiles from #job-board, matches jobs using Claude,
and sends personalised 1-2 job recommendations to each member via Slack DM.
"""

import os
import re
import json
import logging
import requests

log = logging.getLogger(__name__)

SLACK_BOT_TOKEN  = os.environ["SLACK_BOT_TOKEN"]
SEEKING_CHANNEL_ID = os.environ.get("SEEKING_CHANNEL_ID", "C0AD3CPTN6Q")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json",
}


# ── 1. Read profiles from #job-board ─────────────────────────────────────────

def fetch_profiles() -> list[dict]:
    """
    Reads the last 200 messages from #job-board and extracts
    'Seeking Opportunity' workflow submissions.
    """
    log.info("Fetching profiles from #job-board…")
    profiles = []
    cursor = None

    while True:
        params = {
            "channel": SEEKING_CHANNEL_ID,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        r = requests.get(
            "https://slack.com/api/conversations.history",
            headers=SLACK_HEADERS,
            params=params,
            timeout=15,
        )
        data = r.json()
        if not data.get("ok"):
            log.error(f"Slack API error: {data.get('error')}")
            break

        for msg in data.get("messages", []):
            profile = parse_profile(msg)
            if profile:
                profiles.append(profile)

        # Only fetch one page — last 200 messages is enough
        break

    log.info(f"Found {len(profiles)} member profiles")
    return profiles


def parse_profile(msg: dict) -> dict | None:
    """
    Parses a Slack workflow message into a structured profile dict.
    Expects fields: Slack Handle, Your Location, Industry or Field,
    Desired Role, Years of Experience, Pitch Yourself...
    """
    text = msg.get("text", "")

    # Only process "Seeking Opportunity" workflow posts
    if "Seeking Opportunity" not in text and "seeking opportunity" not in text.lower():
        # Also check attachments/blocks
        blocks = msg.get("blocks", [])
        block_text = " ".join(
            el.get("text", {}).get("text", "")
            for b in blocks
            for el in (b.get("elements", []) or [b])
            if isinstance(el, dict)
        )
        if "Seeking Opportunity" not in block_text:
            return None

    # Extract fields using regex
    def extract(label: str, src: str) -> str:
        m = re.search(rf"{re.escape(label)}\s*\n([^\n]+)", src, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    # Try to get full text from blocks if plain text is empty
    full_text = text
    if not full_text:
        blocks = msg.get("blocks", [])
        parts = []
        for b in blocks:
            for el in b.get("elements", [b]):
                if isinstance(el, dict) and el.get("text"):
                    t = el["text"]
                    if isinstance(t, dict):
                        parts.append(t.get("text", ""))
                    else:
                        parts.append(str(t))
        full_text = "\n".join(parts)

    slack_handle = extract("Slack Handle", full_text)
    location     = extract("Your Location", full_text)
    industry     = extract("Industry or Field", full_text)
    desired_role = extract("Desired Role", full_text)
    experience   = extract("Years of Experience", full_text)
    pitch        = extract("Pitch Yourself", full_text)

    if not desired_role and not slack_handle:
        return None

    # Resolve @mention to user ID
    user_id = None
    mention_match = re.search(r"<@([A-Z0-9]+)>", full_text)
    if mention_match:
        user_id = mention_match.group(1)

    return {
        "user_id":      user_id,
        "slack_handle": slack_handle,
        "location":     location,
        "industry":     industry,
        "desired_role": desired_role,
        "experience":   experience,
        "pitch":        pitch,
    }


# ── 2. Match jobs to profile using Claude ────────────────────────────────────

def match_jobs(profile: dict, jobs: list[dict]) -> list[dict]:
    """
    Matches jobs to a member profile using keyword scoring.
    Scores each job by how many words from the desired role / industry
    appear in the job title, then returns the top 2.
    """
    if not jobs:
        return []

    desired = (profile.get("desired_role", "") + " " + profile.get("industry", "")).lower()
    keywords = [w for w in re.split(r'\W+', desired) if len(w) > 2]

    def score(job):
        title = job.get("title", "").lower()
        return sum(1 for k in keywords if k in title)

    scored = sorted(jobs, key=score, reverse=True)
    # Return top 2 that have at least 1 keyword match, fallback to top 2 overall
    matches = [j for j in scored if score(j) > 0][:2]
    return matches if matches else scored[:2]


# ── 3. Send DM ────────────────────────────────────────────────────────────────

def open_dm(user_id: str) -> str | None:
    """Opens a DM channel with a user and returns the channel ID."""
    r = requests.post(
        "https://slack.com/api/conversations.open",
        headers=SLACK_HEADERS,
        json={"users": user_id},
        timeout=10,
    )
    data = r.json()
    if data.get("ok"):
        return data["channel"]["id"]
    log.warning(f"Could not open DM with {user_id}: {data.get('error')}")
    return None


def send_dm(user_id: str, profile: dict, matched_jobs: list[dict]):
    """Sends a personalised DM with matched job recommendations."""
    if not user_id:
        log.warning(f"No user ID for {profile.get('slack_handle')} — skipping DM")
        return

    if DRY_RUN:
        log.info(f"[DRY RUN] Would DM {profile.get('slack_handle')} ({user_id}):")
        for job in matched_jobs:
            log.info(f"  → {job['title']} at {job['company']} | {job.get('url','')}")
        return

    dm_channel = open_dm(user_id)
    if not dm_channel:
        return

    name = profile.get("slack_handle", "there").lstrip("@").split()[0]
    role = profile.get("desired_role", "your target role")

    job_blocks = []
    for job in matched_jobs:
        url = job.get("url", "")
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "Remote")
        link = f"<{url}|{title}>" if url else title

        job_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"• *{link}*\n  {company}  —  {location}",
            },
        })

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"👋 Hey {name}! I'm *EAC Job Bot*.\n\n"
                    f"Based on your profile _{role}_, here are this week's top picks for you:"
                ),
            },
        },
        {"type": "divider"},
        *job_blocks,
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "These roles are O-1 friendly. Always verify visa sponsorship directly with the employer. Good luck! 🚀",
                }
            ],
        },
    ]

    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json={"channel": dm_channel, "blocks": blocks},
        timeout=10,
    )
    if r.json().get("ok"):
        log.info(f"DM sent to {profile.get('slack_handle')}")
    else:
        log.warning(f"DM failed for {profile.get('slack_handle')}: {r.json().get('error')}")


# ── 4. Main entry point ───────────────────────────────────────────────────────

def run_dm_flow(jobs: list[dict]):
    """
    Called after the main scraper run with the full job list.
    Reads profiles, matches jobs, sends DMs.
    """
    log.info("Starting DM flow…")
    profiles = fetch_profiles()

    if not profiles:
        log.info("No profiles found — skipping DMs.")
        return

    for profile in profiles:
        try:
            matched = match_jobs(profile, jobs)
            if matched:
                send_dm(profile["user_id"], profile, matched)
            else:
                log.info(f"No matches for {profile.get('slack_handle')}")
        except Exception as e:
            log.error(f"DM flow failed for {profile.get('slack_handle')}: {e}")

    log.info("DM flow complete.")
