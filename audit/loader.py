"""
Load all CSV data files and build lookup structures shared across checks.
"""
import csv
import os
from collections import defaultdict
from typing import Optional

DATA_DIR = os.environ.get("DATA_DIR", "data/v3")
DATA_VERSION = os.path.basename(DATA_DIR.rstrip("/"))

_cache: Optional[dict] = None

# Minimum number of Slack messages in a day to consider the user "active"
SLACK_ACTIVE_THRESHOLD = 3


def load_csv(fname: str) -> list[dict]:
    with open(os.path.join(DATA_DIR, fname)) as f:
        return list(csv.DictReader(f))


def load_all() -> dict:
    """
    Load all source CSVs and build lookup dicts.
    Returns a dict with raw rows and all derived lookups.
    Cached after first call.
    """
    global _cache
    if _cache is not None:
        return _cache

    ts          = load_csv("kimai_timesheets.csv")
    employees   = load_csv("hr_employees.csv")
    assigns     = load_csv("hr_assignments.csv")
    leaves      = load_csv("hr_leave.csv")
    projects    = load_csv("pm_projects.csv")
    slack       = load_csv("slack_activity.csv")
    git_commits = load_csv("git_commits.csv")
    calendar    = load_csv("calendar_events.csv")

    emp_rate   = {e["username"]: e.get("rate", "").strip() for e in employees}
    emp_status = {e["username"]: e.get("status", "").strip() for e in employees}

    user_projs: dict[str, set] = defaultdict(set)
    for a in assigns:
        user_projs[a["user"]].add(a["project"])

    approved_leave: set[tuple] = set()
    for l in leaves:
        if l.get("status", "").strip().lower() == "approved":
            approved_leave.add((l["user"], l["date"]))

    proj_status: dict[str, str] = {}
    for p in projects:
        pname = p.get("project_name") or p.get("name", "")
        proj_status[pname] = p.get("status", "").strip()

    # slack_activity.csv: pre-aggregated — one row per (user, date) with messages count
    slack_active: dict[tuple, int] = {
        (s["user"].strip(), s["date"].strip()): int(s.get("messages", 0))
        for s in slack
        if int(s.get("messages", 0)) >= SLACK_ACTIVE_THRESHOLD
    }

    # git_commits.csv: (user, date) pairs with any commits
    git_active: set[tuple] = {
        (g["user"].strip(), g["date"].strip()) for g in git_commits
    }

    _cache = {
        "ts":             ts,
        "emp_rate":       emp_rate,
        "emp_status":     emp_status,
        "user_projs":     user_projs,
        "approved_leave": approved_leave,
        "proj_status":    proj_status,
        "slack_active":   slack_active,
        "git_active":     git_active,
        "calendar":       calendar,
    }
    return _cache
