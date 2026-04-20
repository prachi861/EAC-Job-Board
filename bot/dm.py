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
    Returns 2 matched jobs:
    - 1 local/remote match (prioritising the member's city/state)
    - 1 best role match from anywhere in the US
    """
    if not jobs:
        return []

    desired = (profile.get("desired_role", "") + " " + profile.get("industry", "")).lower()
    keywords = [w for w in re.split(r'\W+', desired) if len(w) > 2]

    profile_loc = profile.get("location", "").lower()
    loc_parts = [p.strip().lower() for p in re.split(r'[,.]', profile_loc) if p.strip()]
    specific_locs = [l for l in loc_parts if l not in ("usa", "us", "united states", "remote", "willing to relocate", "")]

    def role_score(job):
        title = job.get("title", "").lower()
        return sum(1 for k in keywords if k in title)

    def is_local_or_remote(job):
        loc = job.get("location", "").lower()
        return "remote" in loc or any(l in loc for l in specific_locs)

    sorted_jobs = sorted(jobs, key=role_score, reverse=True)

    local_match = next((j for j in sorted_jobs if is_local_or_remote(j)), None)
    other_match = next((j for j in sorted_jobs if j != local_match), None)

    results = [j for j in [local_match, other_match] if j is not None]
    return results if results else sorted_jobs[:2]


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
    cursor = None

    while True:
        params = {"channel": SEEKING_CHANNEL_ID, "limit": 200}
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
            profile = parse_profile(msg) or parse_freeform_profile(msg)
            if profile:
                handle = profile.get("slack_handle", "")
                if "eac team" in handle.lower():
                    continue
                profiles.append(profile)

        next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if next_cursor:
            cursor = next_cursor
            log.info("Fetching next page of messages…")
        else:
            break

    log.info(f"Found {len(profiles)} member profiles")
    return profiles


# ── 4. Admin preview ──────────────────────────────────────────────────────────

def post_admin_preview(profile: dict, matched_jobs: list[dict]):
    if not ADMIN_CHANNEL_ID:
        log.warning("ADMIN_CHANNEL_ID not set — skipping preview")
        return

    user_id  = profile.get("user_id", "")
    name     = f"<@{user_id}>" if user_id else profile.get("slack_handle", "Unknown")
    role     = profile.get("desired_role", "Unknown role")
    location = profile.get("location", "Location unknown")

    job_lines = []
    for job in matched_jobs:
        url   = job.get("url", "")
        title = job.get("title", "")
        co    = job.get("company", "")
        loc   = job.get("location", "Remote")
        link  = f"<{url}|{title}>" if url else title
        job_lines.append(f"> • {link} at *{co}* — {loc}")

    text = (
        f":mailbox_with_mail: *Proposed DM* → {name}\n"
        f"> *Role:* {role}\n"
        f"> *Location:* {location}\n"
        f"> *Matches:*\n" + "\n".join(job_lines)
    )

    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json={"channel": ADMIN_CHANNEL_ID, "text": text},
        timeout=10,
    )
    result = r.json()
    if result.get("ok"):
        log.info(f"Preview posted for {name}")
    else:
        log.warning(f"Preview post failed for {name}: {result.get('error')}")


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

    name        = profile.get("slack_handle", "there").lstrip("@").split()[0]
    role        = profile.get("desired_role", "your target role")
    is_freeform = profile.get("freeform", False)

    intro = (
        f"👋 Hey {name}!\nI saw your post in #job-board — here are some roles this week that might be a great fit for you:"
        if is_freeform else
        f"👋 Hey {name}!\nBased on your profile as a *{role}*, we found some roles this week that might be a great fit for you:"
    )

    job_lines = []
    for job in matched_jobs:
        url   = job.get("url", "")
        title = job.get("title", "")
        co    = job.get("company", "")
        loc   = job.get("location", "Remote")
        link  = f"<{url}|{title}>" if url else title
        job_lines.append(f"🔹 {link}\n*{co}* — {loc}")

    footer = "✨ These companies are known to sponsor O-1 visas. Always verify sponsorship directly with the employer. Good luck! 🚀"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": intro}},
        {"type": "divider"},
        *[{"type": "section", "text": {"type": "mrkdwn", "text": line}} for line in job_lines],
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]},
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
