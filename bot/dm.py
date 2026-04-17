"""
DM flow — reads member profiles from #job-board, matches jobs using Claude,
and sends personalised 1-2 job recommendations to each member via Slack DM.
"""

import os
import re
import logging
import requests

log = logging.getLogger(__name__)

SLACK_BOT_TOKEN  = os.environ["SLACK_BOT_TOKEN"]
SEEKING_CHANNEL_ID = os.environ.get("SEEKING_CHANNEL_ID", "C0AD3CPTN6Q")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID", "")  # #job-bot-test channel ID
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
            if not profile:
                profile = parse_freeform_profile(msg)
            if profile:
                profiles.append(profile)

        # Only fetch one page — last 200 messages is enough
        break

    log.info(f"Found {len(profiles)} member profiles")
    return profiles


def parse_profile(msg: dict) -> dict | None:
    """
    Parses a Slack workflow message into a structured profile dict.
    Fields are all on one line separated by field label keywords.
    """
    # Gather all text from the message
    full_text = msg.get("text", "")
    if not full_text:
        blocks = msg.get("blocks", [])
        parts = []
        for b in blocks:
            for el in b.get("elements", [b]):
                if isinstance(el, dict) and el.get("text"):
                    t = el["text"]
                    parts.append(t.get("text", "") if isinstance(t, dict) else str(t))
        full_text = " ".join(parts)

    if not full_text:
        return None

    # Only process "Seeking Opportunity" posts
    if "seeking opportunity" not in full_text.lower():
        return None

    # Fields appear in order — extract value between one label and the next
    FIELDS = [
        "Slack Handle",
        "Your Location",
        "Industry or Field",
        "Desired Role",
        "Years of Experience",
        "Link to Portfolio",
        "Pitch Yourself For Your Dream Job In One Sentence",
    ]

    def extract_between(src: str, start_label: str, end_label: str | None) -> str:
        pattern = (
            rf"{re.escape(start_label)}\s*(.+?)\s*{re.escape(end_label)}"
            if end_label
            else rf"{re.escape(start_label)}\s*(.+?)$"
        )
        m = re.search(pattern, src, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    values = {}
    for i, label in enumerate(FIELDS):
        next_label = FIELDS[i + 1] if i + 1 < len(FIELDS) else None
        values[label] = extract_between(full_text, label, next_label)

    slack_handle = values.get("Slack Handle", "")
    location     = values.get("Your Location", "")
    industry     = values.get("Industry or Field", "")
    desired_role = values.get("Desired Role", "")
    experience   = values.get("Years of Experience", "")
    pitch        = values.get("Pitch Yourself For Your Dream Job In One Sentence", "")

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

def parse_freeform_profile(msg: dict) -> dict | None:
    """
    Fallback parser for non-workflow posts from members looking for jobs.
    Detects job-seeking intent and extracts role keywords from free text.
    """
    full_text = msg.get("text", "")
    if not full_text or len(full_text) < 50:
        return None

    # Must show job-seeking intent
    intent_keywords = [
        "looking for", "seeking", "open to", "job search", "laid off",
        "let go", "restructur", "opportunities", "hiring", "connect with",
        "referral", "openings", "job hunting", "available for",
    ]
    t = full_text.lower()
    if not any(k in t for k in intent_keywords):
        return None

    # Skip workflow posts — those are handled by parse_profile
    if "seeking opportunity" in t:
        return None

    # Extract role keywords from text
    ROLE_TERMS = [
        "software engineer", "backend", "frontend", "full stack", "data engineer",
        "data analyst", "data scientist", "machine learning", "ai engineer",
        "product manager", "product owner", "product designer", "ux", "ui",
        "business analyst", "analytics", "devops", "platform engineer",
        "finance", "fp&a", "strategy", "mechanical engineer", "process engineer",
        "project manager", "program manager", "research engineer",
    ]
    found_roles = [r for r in ROLE_TERMS if r in t]
    desired_role = ", ".join(found_roles) if found_roles else "open to opportunities"

    # Extract LinkedIn URL if present
    linkedin = ""
    link_match = re.search(r"https?://(?:www\.)?linkedin\.com/in/[^\s>]+", full_text)
    if link_match:
        linkedin = link_match.group(0)

    # Resolve @mention or use message sender
    user_id = msg.get("user")
    mention_match = re.search(r"<@([A-Z0-9]+)>", full_text)
    if mention_match:
        user_id = mention_match.group(1)

    # Extract name if message starts with it (e.g. "Husna Shahid [1:43 PM]")
    # In Slack API the sender's user ID is in msg["user"]
    return {
        "user_id":      user_id,
        "slack_handle": f"<@{user_id}>" if user_id else "",
        "location":     "",  # unknown — treat as willing to relocate
        "industry":     "open",
        "desired_role": desired_role,
        "experience":   "",
        "pitch":        full_text[:200],
        "freeform":     True,
        "linkedin":     linkedin,
    }



    """
    Matches jobs to a member profile using keyword + location scoring.
    Scores each job by role keywords and location preference, returns top 2.
    """
    if not jobs:
        return []

    desired = (profile.get("desired_role", "") + " " + profile.get("industry", "")).lower()
    keywords = [w for w in re.split(r'\W+', desired) if len(w) > 2]

    profile_loc = profile.get("location", "").lower()
    willing_to_relocate = "relocat" in profile_loc
    # Extract state/city from location e.g. "MN, USA" → "mn"
    loc_parts = [p.strip().lower() for p in re.split(r'[,.]', profile_loc) if p.strip()]
    specific_locs = [l for l in loc_parts if l not in ("usa", "us", "united states", "remote")]

    def score(job):
        title = job.get("title", "").lower()
        job_loc = job.get("location", "").lower()

        # Role keyword score
        role_score = sum(1 for k in keywords if k in title)

        # Location score
        if "remote" in job_loc:
            loc_score = 2  # remote works for everyone
        elif willing_to_relocate:
            loc_score = 1  # any US location is fine
        elif any(l in job_loc for l in specific_locs):
            loc_score = 3  # exact location match gets highest score
        else:
            loc_score = 0  # wrong location, deprioritize

        return role_score + loc_score

    scored = sorted(jobs, key=score, reverse=True)
    matches = [j for j in scored if score(j) > 0][:2]
    return matches if matches else scored[:2]


# ── 3. Send DM ────────────────────────────────────────────────────────────────

def post_admin_preview(profile: dict, matched_jobs: list[dict]):
    """Posts a preview of what would be DMed to the admin channel."""
    if not ADMIN_CHANNEL_ID:
        return
    name = profile.get("slack_handle", "unknown")
    role = profile.get("desired_role", "unknown")
    lines = [f"*Preview DM → {name}* (_{role}_)"]
    for job in matched_jobs:
        url = job.get("url", "")
        title = job.get("title", "")
        company = job.get("company", "")
        loc = job.get("location", "Remote")
        link = f"<{url}|{title}>" if url else title
        lines.append(f"  • *{link}* at {company} — {loc}")

    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json={
            "channel": ADMIN_CHANNEL_ID,
            "text": "\n".join(lines),
        },
        timeout=10,
    )
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
                post_admin_preview(profile, matched)  # always post preview
                if not DRY_RUN:
                    send_dm(profile["user_id"], profile, matched)
            else:
                log.info(f"No matches for {profile.get('slack_handle')}")
        except Exception as e:
            log.error(f"DM flow failed for {profile.get('slack_handle')}: {e}")

    log.info("DM flow complete.")
