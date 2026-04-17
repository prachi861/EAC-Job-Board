"""
DM flow — reads member profiles from #job-board, matches jobs using keyword
scoring, and sends personalised 1-2 job recommendations via Slack DM.
"""

import os
import re
import logging
import requests

log = logging.getLogger(__name__)

SLACK_BOT_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
SEEKING_CHANNEL_ID = os.environ.get("SEEKING_CHANNEL_ID", "C0AD3CPTN6Q")
ADMIN_CHANNEL_ID   = os.environ.get("ADMIN_CHANNEL_ID", "")
DRY_RUN            = os.environ.get("DRY_RUN", "false").lower() == "true"

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json",
}


# ── 1. Job matching ───────────────────────────────────────────────────────────

def match_jobs(profile: dict, jobs: list[dict]) -> list[dict]:
    """
    Matches jobs to a member profile using keyword + location scoring.
    Returns top 2 matches.
    """
    if not jobs:
        return []

    desired = (profile.get("desired_role", "") + " " + profile.get("industry", "")).lower()
    keywords = [w for w in re.split(r'\W+', desired) if len(w) > 2]

    profile_loc = profile.get("location", "").lower()
    willing_to_relocate = "relocat" in profile_loc or not profile_loc
    loc_parts = [p.strip().lower() for p in re.split(r'[,.]', profile_loc) if p.strip()]
    specific_locs = [l for l in loc_parts if l not in ("usa", "us", "united states", "remote", "")]

    def score(job):
        title   = job.get("title", "").lower()
        job_loc = job.get("location", "").lower()
        role_score = sum(1 for k in keywords if k in title)
        if "remote" in job_loc:
            loc_score = 2
        elif willing_to_relocate:
            loc_score = 1
        elif any(l in job_loc for l in specific_locs):
            loc_score = 3
        else:
            loc_score = 0
        return role_score + loc_score

    scored = sorted(jobs, key=score, reverse=True)
    matches = [j for j in scored if score(j) > 0][:2]
    return matches if matches else scored[:2]


# ── 2. Profile parsers ────────────────────────────────────────────────────────

def parse_profile(msg: dict) -> dict | None:
    """Parses a structured 'Seeking Opportunity' workflow post."""
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

    if "seeking opportunity" not in full_text.lower():
        return None

    FIELDS = [
        "Slack Handle",
        "Your Location",
        "Industry or Field",
        "Desired Role",
        "Years of Experience",
        "Link to Portfolio",
        "Pitch Yourself For Your Dream Job In One Sentence",
    ]

    def extract_between(src, start_label, end_label):
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
    desired_role = values.get("Desired Role", "")

    if not desired_role and not slack_handle:
        return None

    user_id = msg.get("user")
    mention_match = re.search(r"<@([A-Z0-9]+)>", full_text)
    if mention_match:
        user_id = mention_match.group(1)

    return {
        "user_id":      user_id,
        "slack_handle": slack_handle,
        "location":     values.get("Your Location", ""),
        "industry":     values.get("Industry or Field", ""),
        "desired_role": desired_role,
        "experience":   values.get("Years of Experience", ""),
        "pitch":        values.get("Pitch Yourself For Your Dream Job In One Sentence", ""),
        "freeform":     False,
    }


def parse_freeform_profile(msg: dict) -> dict | None:
    """Fallback parser for non-workflow job-seeking posts."""
    full_text = msg.get("text", "")
    if not full_text or len(full_text) < 50:
        return None

    intent_keywords = [
        "looking for", "seeking", "open to", "job search", "laid off",
        "let go", "restructur", "opportunities", "hiring", "connect with",
        "referral", "openings", "job hunting", "available for",
    ]
    t = full_text.lower()
    if not any(k in t for k in intent_keywords):
        return None

    if "seeking opportunity" in t:
        return None

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

    user_id = msg.get("user")
    mention_match = re.search(r"<@([A-Z0-9]+)>", full_text)
    if mention_match:
        user_id = mention_match.group(1)

    return {
        "user_id":      user_id,
        "slack_handle": f"<@{user_id}>" if user_id else "",
        "location":     "",
        "industry":     "open",
        "desired_role": desired_role,
        "experience":   "",
        "pitch":        full_text[:200],
        "freeform":     True,
    }


# ── 3. Read profiles from #job-board ─────────────────────────────────────────

def fetch_profiles() -> list[dict]:
    log.info("Fetching profiles from #job-board…")
    profiles = []

    r = requests.get(
        "https://slack.com/api/conversations.history",
        headers=SLACK_HEADERS,
        params={"channel": SEEKING_CHANNEL_ID, "limit": 200},
        timeout=15,
    )
    data = r.json()
    if not data.get("ok"):
        log.error(f"Slack API error: {data.get('error')}")
        return profiles

    for msg in data.get("messages", []):
        profile = parse_profile(msg) or parse_freeform_profile(msg)
        if profile:
            profiles.append(profile)

    log.info(f"Found {len(profiles)} member profiles")
    return profiles


# ── 4. Admin preview ──────────────────────────────────────────────────────────

def post_admin_preview(profile: dict, matched_jobs: list[dict]):
    if not ADMIN_CHANNEL_ID:
        return
    name = profile.get("slack_handle") or f"<@{profile.get('user_id', 'unknown')}>"
    role = profile.get("desired_role", "unknown")
    lines = [f"*Preview DM → {name}* (_{role}_)"]
    for job in matched_jobs:
        url   = job.get("url", "")
        title = job.get("title", "")
        co    = job.get("company", "")
        loc   = job.get("location", "Remote")
        link  = f"<{url}|{title}>" if url else title
        lines.append(f"  • *{link}* at {co} — {loc}")
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json={"channel": ADMIN_CHANNEL_ID, "text": "\n".join(lines)},
        timeout=10,
    )


# ── 5. Send DM ────────────────────────────────────────────────────────────────

def open_dm(user_id: str) -> str | None:
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
    if not user_id:
        log.warning(f"No user ID for {profile.get('slack_handle')} — skipping DM")
        return

    dm_channel = open_dm(user_id)
    if not dm_channel:
        return

    name = profile.get("slack_handle", "there").lstrip("@").split()[0]
    role = profile.get("desired_role", "your target role")
    is_freeform = profile.get("freeform", False)

    intro = (
        f"👋 Hey {name}! I'm *EAC Job Bot*.\n\nI saw your post in #job-board — here are this week's top picks that might be a fit for you:"
        if is_freeform else
        f"👋 Hey {name}! I'm *EAC Job Bot*.\n\nBased on your profile _{role}_, here are this week's top picks for you:"
    )

    job_blocks = []
    for job in matched_jobs:
        url   = job.get("url", "")
        title = job.get("title", "")
        co    = job.get("company", "")
        loc   = job.get("location", "Remote")
        link  = f"<{url}|{title}>" if url else title
        job_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"• *{link}*\n  {co}  —  {loc}"},
        })

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": intro}},
        {"type": "divider"},
        *job_blocks,
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "These roles are O-1 friendly. Always verify visa sponsorship directly with the employer. Good luck! 🚀"}]},
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


# ── 6. Main entry point ───────────────────────────────────────────────────────

def run_dm_flow(jobs: list[dict]):
    log.info("Starting DM flow…")
    profiles = fetch_profiles()

    if not profiles:
        log.info("No profiles found — skipping DMs.")
        return

    for profile in profiles:
        try:
            matched = match_jobs(profile, jobs)
            if matched:
                post_admin_preview(profile, matched)
                if not DRY_RUN:
                    send_dm(profile["user_id"], profile, matched)
            else:
                log.info(f"No matches for {profile.get('slack_handle')}")
        except Exception as e:
            log.error(f"DM flow failed for {profile.get('slack_handle')}: {e}")

    log.info("DM flow complete.")
