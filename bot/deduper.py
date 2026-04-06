"""Cross-week deduplication — tracks posted jobs in data/seen_jobs.json."

import json
from pathlib import Path

SEEN_PATH = Path("data/seen_jobs.json")

def _load() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()

def _key(job: dict) -> str:
    return f"{job.get('title','').lower()}||{job.get('company','').lower()}"

def filter_new(jobs: list[dict]) -> list[dict]:
    seen = _load()
    return [j for j in jobs if _key(j) not in seen]

def mark_seen(jobs: list[dict]):
    seen = _load()
    for j in jobs:
        seen.add(_key(j))
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(list(seen), indent=2))