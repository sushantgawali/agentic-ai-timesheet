# /timesheet:load-data

## Overview

Validates that all required data sources are present and prints a structured
summary of each file. Run this first to confirm your data is complete and
well-formed before running an audit.

---

## Usage

```
/timesheet:load-data
```

No arguments. Read-only — does not modify any files.

### Example output

```
=== DATA_SUMMARY ===
  kimai_timesheets.csv : 159 rows | columns: [user, date, begin, end, hours, ...]
  slack_activity.csv   :  139 rows | ...
  ...

=== EMPLOYEE_TABLE ===
  john: role=developer rate=75 status=active tz=America/New_York
  alice: role=designer rate=80 status=deactivated tz=Europe/London
  ...

=== TIMESHEET_OVERVIEW ===
  Total entries : 159
  Users         : ['admin', 'alice', 'bob', 'jane', 'john']
  Date range    : 2026-03-02 → 2026-03-31
  Empty fields  : {'activity': 8, 'description': 11, 'project': 1, ...}
```

---

## Implementation

### Required files

The command checks for exactly 8 files in `data/`:

| File | Purpose |
|------|---------|
| `kimai_timesheets.csv` | Primary timesheet data (source of truth for auditing) |
| `hr_employees.csv` | Employee roles, canonical rates, status, timezone |
| `hr_assignments.csv` | Which users are assigned to which projects |
| `hr_leave.csv` | Approved leave dates per user |
| `pm_projects.csv` | Project status and budget |
| `slack_activity.csv` | Daily Slack message counts per user |
| `git_commits.csv` | Daily git commit counts per user |
| `calendar_events.csv` | Calendar events per user (loaded, not yet used in audit) |

If any file is missing the command prints a `FATAL` error and stops.

### Sections printed

| Section | What it shows |
|---------|---------------|
| `DATA_SUMMARY` | Row count and column names for every file |
| `EMPLOYEE_TABLE` | Username, role, rate, status, timezone for each employee |
| `ASSIGNMENTS_TABLE` | Projects each user is assigned to |
| `LEAVE_TABLE` | All leave records with type and approval status |
| `PROJECT_TABLE` | Project name, status, end date, budget hours |
| `TIMESHEET_OVERVIEW` | Entry count, user list, date range, empty field counts |

### Known column name quirks

The script normalises two column name discrepancies in the raw CSVs:

- `pm_projects.csv` — uses `name` (not `project_name`)
- `hr_leave.csv` — uses `type` (not `leave_type`)

Both are handled transparently with `p.get('project_name') or p.get('name')`.
