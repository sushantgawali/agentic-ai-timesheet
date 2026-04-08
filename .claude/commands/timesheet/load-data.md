Load and validate all timesheet data sources before running an audit.

## Instructions

Using the Bash tool with python3 (stdlib only — no pip), scan ALL CSV files in the
`data/` directory, infer their semantic roles from column headers, and produce a
structured summary. Do NOT modify any files.

### Step 1 — Discover and classify all CSV files

Run this python3 script via Bash:

```python
import csv, os, sys
from collections import defaultdict

DATA_DIR = os.environ.get("DATA_DIR", "data")

def read_headers(path):
    try:
        with open(path) as f:
            return next(csv.reader(f), [])
    except Exception:
        return []

def infer_role(filename, columns):
    cols = {c.lower().strip() for c in columns}
    fname = filename.lower().replace(".csv", "")
    if ("begin" in cols or "start" in cols) and "end" in cols and ("hours" in cols or "duration" in cols):
        return "timesheets"
    if "from_email" in cols or "to_email" in cols:
        return "emails"
    if "date" in cols and "name" in cols and "user" not in cols and any(k in fname for k in ("holiday",)):
        return "holidays"
    if "date" in cols and "name" in cols and "type" in cols and "user" not in cols:
        return "holidays"
    if "user" in cols and "date" in cols and ("text" in cols or "ts" in cols or "channel" in cols) and "messages" not in cols:
        return "slack (raw messages)"
    if "messages" in cols and "user" in cols and "date" in cols:
        return "slack (pre-aggregated)"
    if "user" in cols and ("commits" in cols or any(k in fname for k in ("git", "commit"))):
        return "git"
    if "username" in cols and ("rate" in cols or "status" in cols):
        return "employees"
    if any(k in fname for k in ("calendar_leave", "leave_calendar")) and "user" in cols and "date" in cols:
        return "calendar_leave"
    if any(k in fname for k in ("leave", "pto", "vacation", "absence")) and "user" in cols and "date" in cols:
        return "leave"
    if "user" in cols and "project" in cols and "begin" not in cols and "messages" not in cols and "text" not in cols:
        return "assignments"
    if "user" in cols and "date" in cols and "status" in cols and "project" not in cols and "text" not in cols and "title" not in cols:
        return "leave"
    if ("project_name" in cols or "name" in cols) and "status" in cols and "user" not in cols:
        return "projects"
    if any(k in fname for k in ("calendar", "event")):
        return "calendar"
    if any(k in cols for k in ("title", "summary", "event_type")) and "user" in cols:
        return "calendar"
    return "UNKNOWN"

def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))

if not os.path.isdir(DATA_DIR):
    print(f"FATAL: DATA_DIR not found: {DATA_DIR}")
    sys.exit(1)

csv_files = sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".csv"))
if not csv_files:
    print(f"FATAL: No CSV files found in {DATA_DIR}")
    sys.exit(1)

print(f"=== DATA DISCOVERY — {DATA_DIR} ===")
print(f"Found {len(csv_files)} CSV file(s):\n")

role_map = {}
for fname in csv_files:
    path = os.path.join(DATA_DIR, fname)
    headers = read_headers(path)
    rows = load(path)
    role = infer_role(fname, headers)
    if role not in role_map:
        role_map[role] = path
    flag = " ⚠ UNKNOWN ROLE" if role == "UNKNOWN" else ""
    print(f"  {fname}")
    print(f"    Role     : {role}{flag}")
    print(f"    Rows     : {len(rows)}")
    print(f"    Columns  : {headers}")
    print()

# Summary by role
print("=== ROLE MAP ===")
for role, path in sorted(role_map.items()):
    print(f"  {role:30s} → {os.path.basename(path)}")

unknown = [f for f in csv_files if infer_role(f, read_headers(os.path.join(DATA_DIR, f))) == "UNKNOWN"]
if unknown:
    print(f"\n⚠ Unrecognised files (will not be used in audit): {unknown}")

# Timesheets overview
ts_path = role_map.get("timesheets")
if ts_path:
    ts = load(ts_path)
    dates = [r.get("date","") for r in ts if r.get("date")]
    users = sorted(set(r.get("user","") for r in ts if r.get("user")))
    print(f"\n=== TIMESHEET OVERVIEW ===")
    print(f"  Total entries : {len(ts)}")
    print(f"  Users         : {users}")
    print(f"  Date range    : {min(dates) if dates else 'N/A'} → {max(dates) if dates else 'N/A'}")
    empty = {col: sum(1 for r in ts if not r.get(col,'').strip())
             for col in ['activity','description','project','hourly_rate']}
    print(f"  Empty fields  : {empty}")
else:
    print("\n⚠ No timesheet file detected — audit cannot run.")

# Employees table
emp_path = role_map.get("employees")
if emp_path:
    employees = load(emp_path)
    print(f"\n=== EMPLOYEE TABLE ({len(employees)} employees) ===")
    for e in employees:
        print(f"  {e.get('username','?')}: role={e.get('role','?')} rate={e.get('rate','?')} status={e.get('status','?')}")

print("\n=== END LOAD-DATA ===")
```

After output, tell the user:
"All data loaded. Run /timesheet:audit to find issues, or /timesheet:propose-fixes to jump straight to corrections."
