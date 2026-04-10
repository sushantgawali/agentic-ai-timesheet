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
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from typing import Optional

from audit.email_signals import parse_email_signals as _parse_email_signals

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
# DOCX reader & SOW parser (stdlib only — no python-docx dependency)
# ---------------------------------------------------------------------------

_WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_text(path: str) -> str:
    """
    Extract plain text from a .docx file using stdlib zipfile + xml.etree.
    Returns an empty string on error.
    """
    try:
        with zipfile.ZipFile(path) as z:
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
        lines = []
        for para in tree.iter(f"{_WNS}p"):
            line = "".join(t.text or "" for t in para.iter(f"{_WNS}t"))
            if line.strip():
                lines.append(line.strip())
        return "\n".join(lines)
    except Exception:
        return ""


def _parse_sow_text(text: str) -> dict:
    """
    Parse a SOW document's plain text and return structured fields:
        project_name, client, sow_reference, effective_date, end_date,
        monthly_value, team: [{name, role, allocation, rate, monthly_hours}]
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result: dict = {
        "project_name": None,
        "client": None,
        "sow_reference": None,
        "effective_date": None,
        "end_date": None,
        "monthly_value": None,
        "team": [],
    }
    n = len(lines)

    _STOP_WORDS = {
        "Signatures", "For:", "Name", "KPI", "Target", "#",
        "Deliverable", "Assumptions", "Scope", "Commercial",
        "Invoicing", "Payment",
    }

    i = 0
    while i < n:
        line = lines[i]

        if line == "STATEMENT OF WORK" and i + 1 < n:
            result["project_name"] = lines[i + 1]

        if line.startswith("SOW Reference:"):
            result["sow_reference"] = line.split(":", 1)[1].strip()

        # Client is the line after "Client", before "Vendor"
        if line == "Client" and i + 1 < n and lines[i + 1] not in ("Vendor", "Effective Date", "End Date"):
            result["client"] = lines[i + 1]

        if line == "Effective Date" and i + 1 < n:
            result["effective_date"] = lines[i + 1]

        if line == "End Date" and i + 1 < n:
            result["end_date"] = lines[i + 1]

        if "Estimated monthly value:" in line:
            result["monthly_value"] = line.split(":", 1)[1].strip()

        # Team composition table header pattern
        if (
            line == "Name" and i + 4 < n
            and lines[i + 1] == "Role"
            and lines[i + 2] == "Allocation"
            and "Rate" in lines[i + 3]
            and "Monthly Hours" in lines[i + 4]
        ):
            j = i + 5
            while j + 4 < n:
                name = lines[j]
                if not name or any(sw in name for sw in _STOP_WORDS):
                    break
                rate_str  = lines[j + 3]
                hours_str = lines[j + 4]
                if not ("$" in rate_str or rate_str.replace(",", "").isdigit()):
                    break
                try:
                    rate  = float(rate_str.replace("$", "").replace(",", ""))
                    hours = int(hours_str.replace(",", ""))
                    result["team"].append({
                        "name":          name,
                        "role":          lines[j + 1],
                        "allocation":    lines[j + 2],
                        "rate":          rate,
                        "monthly_hours": hours,
                    })
                    j += 5
                except (ValueError, IndexError):
                    break

        i += 1

    return result


def read_pdf_text(path: str) -> str:
    """
    Extract plain text from a PDF file using pypdf.
    Returns an empty string on error or if pypdf is not installed.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)
    except Exception:
        return ""


def load_guidelines_documents() -> list[dict]:
    """
    Read all policy/guideline documents from DATA_DIR/documents/guidelines/.
    Supports .pdf (via pypdf) and .docx (via stdlib zipfile).

    Returns a list of dicts:
        {filename, path, type ("pdf"|"docx"), text}
    """
    guidelines_dir = os.path.join(DATA_DIR, "documents", "guidelines")
    if not os.path.isdir(guidelines_dir):
        return []
    docs = []
    for entry in sorted(os.listdir(guidelines_dir)):
        lower = entry.lower()
        path = os.path.join(guidelines_dir, entry)
        if not os.path.isfile(path):
            continue
        if lower.endswith(".pdf"):
            text = read_pdf_text(path)
            docs.append({"filename": entry, "path": path, "type": "pdf", "text": text})
        elif lower.endswith(".docx"):
            text = read_docx_text(path)
            docs.append({"filename": entry, "path": path, "type": "docx", "text": text})
    return docs


def load_sow_documents() -> list[dict]:
    """
    Read and parse all .docx files from DATA_DIR/documents/sow/.
    Returns a list of parsed SOW dicts (project_name, team, dates, etc.)
    plus the original filename and raw text.
    """
    sow_dir = os.path.join(DATA_DIR, "documents", "sow")
    if not os.path.isdir(sow_dir):
        return []
    docs = []
    for entry in sorted(os.listdir(sow_dir)):
        if not entry.lower().endswith(".docx"):
            continue
        path = os.path.join(sow_dir, entry)
        text = read_docx_text(path)
        parsed = _parse_sow_text(text)
        docs.append({
            "filename": entry,
            "path":     path,
            "text":     text,
            **parsed,
        })
    return docs


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

    # --- project budget from pm_projects.csv ---
    proj_budget_hours: dict[str, float] = {}
    proj_budget_cost:  dict[str, float] = {}
    for p in projects:
        pname = p.get("project_name") or p.get("name", "")
        if pname:
            try:
                proj_budget_hours[pname] = float(p.get("budget_hours", 0) or 0)
                proj_budget_cost[pname]  = float(p.get("budget_cost",  0) or 0)
            except (ValueError, TypeError):
                pass

    # --- project actuals from timesheets ---
    proj_actual_hours: dict[str, float] = defaultdict(float)
    proj_actual_cost:  dict[str, float] = defaultdict(float)
    for row in ts:
        proj = row.get("project", "").strip()
        if not proj:
            continue
        try:
            h = float(row.get("hours", 0) or 0)
        except (ValueError, TypeError):
            h = 0.0
        # Use the row's hourly_rate first (what was billed); fall back to canonical rate
        try:
            r = float(row.get("hourly_rate", 0) or 0)
        except (ValueError, TypeError):
            r = 0.0
        if not r:
            try:
                r = float(emp_rate.get(row.get("user", ""), 0) or 0)
            except (ValueError, TypeError):
                r = 0.0
        proj_actual_hours[proj] += h
        proj_actual_cost[proj]  += h * r

    # --- SOW documents ---
    sow_data = load_sow_documents()

    # --- Guidelines documents ---
    guidelines_data = load_guidelines_documents()

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
        # Parsed email signals (extra_time, date_extension, client_holiday, escalation, assignment)
        "email_signals":    _parse_email_signals(email_rows),
        # Project budget & actuals
        "proj_budget_hours": proj_budget_hours,
        "proj_budget_cost":  proj_budget_cost,
        "proj_actual_hours": dict(proj_actual_hours),
        "proj_actual_cost":  dict(proj_actual_cost),
        # SOW documents
        "sow_data":          sow_data,
        # Guidelines documents
        "guidelines_data":   guidelines_data,
        # Discovery metadata
        "discovered_files": discovered,
        "role_map":         role_map,
    }
    return _cache


def _reset_cache() -> None:
    """Clear the loader cache (useful for tests or multi-version runs)."""
    global _cache
    _cache = None
