"""
Load all CSV data files and build lookup structures shared across checks.

File discovery: instead of requiring fixed filenames, the loader scans DATA_DIR
for all CSV files and uses column heuristics to assign each one a role.

Supported roles:
    timesheets    — per-entry billing records (begin/end/hours required)
    employees     — HR employee roster (username, rate, status)
    assignments   — user→project authorisation mapping
    leave         — approved leave days (hr_leave.csv style)
    projects      — project catalogue (name/status)
    slack         — Slack activity; handles both:
                      • pre-aggregated (messages column)
                      • raw per-message rows (text/ts column) — auto-aggregated
    git           — Git commit activity (user, date)
    holidays      — Public holidays (date, name) — no user column
    calendar_leave — Leave entries from calendar system (user, date, status, title)
    emails        — Organisational email records (from_email, to_email, date, ...)
    calendar      — Generic calendar/event data

Missing roles degrade gracefully — related checks simply produce no findings.
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


# ---------------------------------------------------------------------------
# File discovery & role inference
# ---------------------------------------------------------------------------

def _read_headers(path: str) -> list[str]:
    """Return the column headers of a CSV file (empty list on error)."""
    try:
        with open(path) as f:
            reader = csv.reader(f)
            return next(reader, [])
    except Exception:
        return []


def infer_file_role(filename: str, columns: list[str]) -> Optional[str]:
    """
    Infer the semantic role of a CSV file from its filename and column names.

    Returns one of the supported role strings, or None if unrecognised.
    """
    cols = {c.lower().strip() for c in columns}
    fname = os.path.basename(filename).lower().replace(".csv", "")

    # --- Timesheets: must have a time-range (begin/start + end) and duration ---
    if ("begin" in cols or "start" in cols) and "end" in cols and (
        "hours" in cols or "duration" in cols or "minutes" in cols
    ):
        return "timesheets"

    # --- Emails: distinctive from/to columns ---
    if "from_email" in cols or "to_email" in cols:
        return "emails"

    # --- Public holidays: date+name but NO user column ---
    if "date" in cols and ("name" in cols or "holiday" in cols) and "user" not in cols:
        if any(k in fname for k in ("holiday", "public_holiday", "bank_holiday")):
            return "holidays"
        # calendar_holidays.csv: has 'type' and 'name', no user
        if "name" in cols and "type" in cols and "user" not in cols:
            return "holidays"

    # --- Slack (raw messages): per-message rows — has text or ts or channel, no messages count ---
    if "user" in cols and "date" in cols and (
        "text" in cols or "ts" in cols or "channel" in cols
    ) and "messages" not in cols:
        return "slack"

    # --- Slack (pre-aggregated): has a messages count column ---
    if "messages" in cols and "user" in cols and "date" in cols:
        return "slack"

    # --- Git: distinctive commits column or filename hint ---
    if "user" in cols and (
        "commits" in cols or any(k in fname for k in ("git", "commit", "vcs"))
    ):
        return "git"
    if "user" in cols and "date" in cols and len(cols) <= 3 and any(k in fname for k in ("git", "commit")):
        return "git"

    # --- Employees: username + rate/status ---
    if "username" in cols and ("rate" in cols or "hourly_rate" in cols or "status" in cols):
        return "employees"
    if any(k in fname for k in ("employee", "staff", "workforce")) and "username" in cols:
        return "employees"

    # --- Calendar leave: leave records sourced from a calendar system ---
    if any(k in fname for k in ("calendar_leave", "leave_calendar")):
        if "user" in cols and "date" in cols:
            return "calendar_leave"

    # --- Leave (filename hint takes priority over column-only detection) ---
    if any(k in fname for k in ("hr_leave", "leave", "pto", "vacation", "absence", "time_off")):
        if "user" in cols and "date" in cols:
            return "leave"

    # --- Assignments: user + project, no time-range fields ---
    if "user" in cols and "project" in cols and "begin" not in cols and "start" not in cols:
        if "messages" not in cols and "commits" not in cols and "text" not in cols:
            return "assignments"

    # --- Leave (column-only, no filename hint) ---
    if (
        "user" in cols and "date" in cols and "status" in cols
        and "begin" not in cols and "start" not in cols
        and "messages" not in cols and "project" not in cols
        and "text" not in cols and "title" not in cols
    ):
        return "leave"

    # --- Projects: project name + status, no per-user columns ---
    if ("project_name" in cols or "name" in cols) and "status" in cols and "user" not in cols:
        return "projects"
    if any(k in fname for k in ("project", "pm_")) and ("status" in cols or "name" in cols):
        return "projects"

    # --- Calendar (generic): event/title columns with user ---
    if any(k in fname for k in ("calendar", "event", "meeting")):
        return "calendar"
    if any(k in cols for k in ("title", "event_title", "summary", "event_type")) and "user" in cols:
        return "calendar"

    return None


def discover_csv_files() -> list[dict]:
    """
    Scan DATA_DIR for all CSV files, read their headers, and infer roles.

    Returns a list of dicts:
        {filename, path, columns, role}
    where role may be None for unrecognised files.
    """
    results = []
    if not os.path.isdir(DATA_DIR):
        return results

    for entry in sorted(os.listdir(DATA_DIR)):
        if not entry.lower().endswith(".csv"):
            continue
        path = os.path.join(DATA_DIR, entry)
        if not os.path.isfile(path):
            continue
        headers = _read_headers(path)
        role = infer_file_role(entry, headers)
        results.append({
            "filename": entry,
            "path": path,
            "columns": headers,
            "role": role,
        })

    return results


# ---------------------------------------------------------------------------
# CSV loading helpers
# ---------------------------------------------------------------------------

def load_csv(path: str) -> list[dict]:
    """Load a single CSV file by absolute path. Returns [] if missing."""
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def _aggregate_slack_raw(rows: list[dict]) -> dict[tuple, int]:
    """
    Aggregate raw per-message Slack rows (user, date, text, ...) into a
    {(user, date): message_count} dict, then filter by SLACK_ACTIVE_THRESHOLD.
    """
    counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        user = r.get("user", "").strip()
        date = r.get("date", "").strip()
        if user and date:
            counts[(user, date)] += 1
    return {
        (user, date): count
        for (user, date), count in counts.items()
        if count >= SLACK_ACTIVE_THRESHOLD
    }


def _aggregate_slack_prebuilt(rows: list[dict]) -> dict[tuple, int]:
    """
    Load pre-aggregated Slack rows (user, date, messages) into a
    {(user, date): message_count} dict, filtered by SLACK_ACTIVE_THRESHOLD.
    """
    result = {}
    for s in rows:
        try:
            count = int(s.get("messages", 0))
        except (ValueError, TypeError):
            count = 0
        if count >= SLACK_ACTIVE_THRESHOLD:
            result[(s["user"].strip(), s["date"].strip())] = count
    return result


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_all() -> dict:
    """
    Discover all CSV files in DATA_DIR, map them to roles via column heuristics,
    load the relevant ones, and return a unified context dict for audit checks.

    Context keys always present (empty collections when data is absent):
        ts, emp_rate, emp_status, user_projs, approved_leave,
        proj_status, slack_active, git_active, calendar,
        public_holidays, calendar_leave_rows, email_rows,
        discovered_files, role_map
    """
    global _cache
    if _cache is not None:
        return _cache

    # --- discover and map (first match per role wins) ---
    discovered = discover_csv_files()
    role_map: dict[str, str] = {}
    for info in discovered:
        role = info["role"]
        if role and role not in role_map:
            role_map[role] = info["path"]

    # --- load each role ---
    ts             = load_csv(role_map.get("timesheets", ""))
    employees      = load_csv(role_map.get("employees", ""))
    assigns        = load_csv(role_map.get("assignments", ""))
    leaves         = load_csv(role_map.get("leave", ""))
    projects       = load_csv(role_map.get("projects", ""))
    slack_rows     = load_csv(role_map.get("slack", ""))
    git_rows       = load_csv(role_map.get("git", ""))
    calendar_rows  = load_csv(role_map.get("calendar", ""))
    holiday_rows   = load_csv(role_map.get("holidays", ""))
    cal_leave_rows = load_csv(role_map.get("calendar_leave", ""))
    email_rows     = load_csv(role_map.get("emails", ""))

    # --- employee lookups ---
    emp_rate   = {e["username"]: e.get("rate", "").strip() for e in employees if "username" in e}
    emp_status = {e["username"]: e.get("status", "").strip() for e in employees if "username" in e}

    # --- project assignments ---
    user_projs: dict[str, set] = defaultdict(set)
    for a in assigns:
        if "user" in a and "project" in a:
            user_projs[a["user"]].add(a["project"])

    # --- approved leave (hr_leave.csv) ---
    approved_leave: set[tuple] = set()
    for l in leaves:
        if l.get("status", "").strip().lower() == "approved":
            if "user" in l and "date" in l:
                approved_leave.add((l["user"], l["date"]))

    # --- calendar_leave.csv as supplementary leave (confirmed / approved entries) ---
    for cl in cal_leave_rows:
        status = cl.get("status", "").strip().lower()
        if status in ("confirmed", "approved"):
            if "user" in cl and "date" in cl:
                approved_leave.add((cl["user"], cl["date"]))

    # --- project catalogue ---
    proj_status: dict[str, str] = {}
    for p in projects:
        pname = p.get("project_name") or p.get("name", "")
        if pname:
            proj_status[pname] = p.get("status", "").strip()

    # --- slack activity (handles both raw and pre-aggregated formats) ---
    slack_cols = set()
    if slack_rows:
        slack_cols = {c.lower().strip() for c in slack_rows[0].keys()}
    if "messages" in slack_cols:
        slack_active = _aggregate_slack_prebuilt(slack_rows)
    else:
        # raw per-message format (v5+)
        slack_active = _aggregate_slack_raw(slack_rows)

    # --- git activity ---
    git_active: set[tuple] = set()
    for g in git_rows:
        if "user" in g and "date" in g:
            git_active.add((g["user"].strip(), g["date"].strip()))

    # --- public holidays as a set of date strings ---
    public_holidays: set[str] = set()
    for h in holiday_rows:
        d = h.get("date", "").strip()
        if d:
            public_holidays.add(d)

    _cache = {
        "ts":               ts,
        "emp_rate":         emp_rate,
        "emp_status":       emp_status,
        "user_projs":       user_projs,
        "approved_leave":   approved_leave,
        "proj_status":      proj_status,
        "slack_active":     slack_active,
        "git_active":       git_active,
        "calendar":         calendar_rows,
        "public_holidays":  public_holidays,
        "calendar_leave_rows": cal_leave_rows,
        "email_rows":       email_rows,
        # Discovery metadata
        "discovered_files": discovered,
        "role_map":         role_map,
    }
    return _cache


def _reset_cache() -> None:
    """Clear the loader cache (useful for tests or multi-version runs)."""
    global _cache
    _cache = None
