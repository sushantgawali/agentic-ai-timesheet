Load and validate all timesheet data sources before running an audit.

## Instructions

Using the Bash tool with python3 (stdlib only — no pip), read every CSV file in the
`data/` directory and produce a structured summary. Do NOT modify any files.

### Step 1 — Verify all required files exist

Check that these 8 files are present in `data/`:
- kimai_timesheets.csv
- slack_activity.csv
- calendar_events.csv
- git_commits.csv
- hr_employees.csv
- hr_assignments.csv
- hr_leave.csv
- pm_projects.csv

Report any missing files as FATAL errors and stop.

### Step 2 — Run this python3 script via Bash

```python
import csv, os, sys
from datetime import datetime

DATA_DIR = "data"
FILES = [
    "kimai_timesheets.csv", "slack_activity.csv", "calendar_events.csv",
    "git_commits.csv", "hr_employees.csv", "hr_assignments.csv",
    "hr_leave.csv", "pm_projects.csv"
]

# --- Verify files ---
missing = [f for f in FILES if not os.path.exists(os.path.join(DATA_DIR, f))]
if missing:
    print("FATAL: Missing files:", missing)
    sys.exit(1)

def load(fname):
    with open(os.path.join(DATA_DIR, fname)) as f:
        rows = list(csv.DictReader(f))
    return rows

# --- DATA_SUMMARY ---
print("=== DATA_SUMMARY ===")
for fname in FILES:
    rows = load(fname)
    print(f"  {fname}: {len(rows)} rows | columns: {list(rows[0].keys()) if rows else 'EMPTY'}")

# --- EMPLOYEE_TABLE ---
employees = load("hr_employees.csv")
print("\n=== EMPLOYEE_TABLE ===")
for e in employees:
    print(f"  {e['username']}: role={e['role']} rate={e.get('rate','?')} status={e['status']} tz={e.get('timezone','?')}")

# --- ASSIGNMENTS_TABLE ---
assignments = load("hr_assignments.csv")
from collections import defaultdict
user_projects = defaultdict(list)
for a in assignments:
    user_projects[a['user']].append(a['project'])
print("\n=== ASSIGNMENTS_TABLE ===")
for u, projs in sorted(user_projects.items()):
    print(f"  {u}: {projs}")

# --- LEAVE_TABLE ---
# hr_leave.csv uses 'type' column (not 'leave_type')
leaves = load("hr_leave.csv")
print("\n=== LEAVE_TABLE ===")
for l in leaves:
    leave_type = l.get('type') or l.get('leave_type', '?')
    print(f"  {l['user']} | {l['date']} | {leave_type} | status={l.get('status','?')}")

# --- PROJECT_TABLE ---
# pm_projects.csv uses 'name' column (not 'project_name')
projects = load("pm_projects.csv")
print("\n=== PROJECT_TABLE ===")
for p in projects:
    pname = p.get('project_name') or p.get('name', '?')
    print(f"  {pname}: status={p.get('status','?')} end={p.get('end_date','?')} budget_hours={p.get('budget_hours','?')}")

# --- TIMESHEET_OVERVIEW ---
ts = load("kimai_timesheets.csv")
dates = [r['date'] for r in ts if r.get('date')]
users = set(r['user'] for r in ts)
print("\n=== TIMESHEET_OVERVIEW ===")
print(f"  Total entries : {len(ts)}")
print(f"  Users         : {sorted(users)}")
print(f"  Date range    : {min(dates)} → {max(dates)}")
print(f"  Empty fields  :", {col: sum(1 for r in ts if not r.get(col,'').strip())
    for col in ['activity','description','project','hourly_rate']})
print("=== END LOAD-DATA ===")
```

After output, tell the user:
"All data loaded. Run /timesheet:audit to find issues, or /timesheet:propose-fixes to jump straight to corrections."
